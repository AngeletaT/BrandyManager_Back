import hashlib
import uuid
import wave
from pathlib import Path

from django.conf import settings
from django.core.files.storage import storages
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.catalog.exceptions import AudioAssetDuplicate, AudioContentCodeConflict, AudioFileInvalid, AudioStorageFailed
from apps.catalog.models import AudioAsset, AudioContent, ProcessingJob, Song, SongTag, UploadSession


ACCEPTED_WAVE_MIME_TYPES = {"audio/wav", "audio/wave", "audio/x-wav", "audio/vnd.wave"}


def _inspect_wave(*, uploaded_file):
    if uploaded_file.size <= 0:
        raise AudioFileInvalid(message="El archivo esta vacio.")
    if uploaded_file.size > settings.BM_AUDIO_MAX_UPLOAD_BYTES:
        raise AudioFileInvalid(message="El archivo supera el tamano maximo permitido.")

    declared_mime = (getattr(uploaded_file, "content_type", "") or "").split(";", 1)[0].lower()
    if declared_mime not in ACCEPTED_WAVE_MIME_TYPES:
        raise AudioFileInvalid(message="Solo se admiten archivos WAV PCM con un tipo MIME valido.")

    uploaded_file.seek(0)
    header = uploaded_file.read(12)
    uploaded_file.seek(0)
    if len(header) != 12 or header[:4] != b"RIFF" or header[8:] != b"WAVE":
        raise AudioFileInvalid(message="El contenido del archivo no corresponde a un WAV real.")

    try:
        with wave.open(uploaded_file, "rb") as wav_file:
            if wav_file.getcomptype() != "NONE":
                raise AudioFileInvalid(message="El WAV debe utilizar audio PCM sin compresion.")
            frame_count = wav_file.getnframes()
            sample_rate = wav_file.getframerate()
            channels = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
    except (EOFError, wave.Error) as exc:
        raise AudioFileInvalid(message="El contenido del WAV esta danado o incompleto.") from exc
    finally:
        uploaded_file.seek(0)

    if frame_count <= 0 or sample_rate <= 0 or channels <= 0 or sample_width <= 0:
        raise AudioFileInvalid(message="El WAV no contiene audio reproducible.")

    checksum = hashlib.sha256()
    for chunk in uploaded_file.chunks():
        checksum.update(chunk)
    uploaded_file.seek(0)
    duration_ms = max(1, round(frame_count * 1000 / sample_rate))
    bitrate_kbps = max(1, round(sample_rate * channels * sample_width * 8 / 1000))
    return {
        "checksum_sha256": checksum.hexdigest(),
        "duration_ms": duration_ms,
        "bitrate_kbps": bitrate_kbps,
        "sample_rate_hz": sample_rate,
        "channels": channels,
    }


def ingest_global_song(*, uploaded_by, data):
    uploaded_file = data["file"]
    technical = _inspect_wave(uploaded_file=uploaded_file)
    internal_code = data["internal_code"].strip().upper()

    if AudioAsset.objects.filter(
        checksum_sha256=technical["checksum_sha256"],
        processing_status=AudioAsset.ProcessingStatus.READY,
    ).exists():
        raise AudioAssetDuplicate()
    if AudioContent.objects.filter(owner_company__isnull=True, internal_code=internal_code).exists():
        raise AudioContentCodeConflict()

    content_id = uuid.uuid4()
    asset_id = uuid.uuid4()
    safe_filename = Path(uploaded_file.name or "audio.wav").name
    storage_key = f"catalog/audio/{content_id}/original/{asset_id}.wav"
    storage = storages[settings.BM_AUDIO_STORAGE_ALIAS]
    saved_key = ""
    now = timezone.now()

    try:
        saved_key = storage.save(storage_key, uploaded_file)
    except Exception as exc:
        raise AudioStorageFailed() from exc

    try:
        with transaction.atomic():
            content = AudioContent.objects.create(
                id=content_id,
                owner_company=None,
                content_type=AudioContent.ContentType.SONG,
                title=data["title"].strip(),
                internal_code=internal_code,
                description=data.get("description", "").strip(),
                visibility=AudioContent.Visibility.GLOBAL,
                status=AudioContent.Status.PROCESSING,
                duration_ms=technical["duration_ms"],
                is_active=True,
                created_by=uploaded_by,
                rights_holder=data["rights_holder"].strip(),
                rights_reference=data["rights_reference"].strip(),
                rights_verified_at=now,
                rights_verified_by=uploaded_by,
            )
            song = Song.objects.create(
                audio_content=content,
                genre=data["genre"],
                ai_generated=True,
                generation_provider=data.get("generation_provider", "").strip(),
                generation_model=data.get("generation_model", "").strip(),
                generation_reference=data.get("generation_reference", "").strip(),
                is_explicit=data.get("is_explicit", False),
            )
            SongTag.objects.bulk_create(
                [SongTag(song=song, tag=tag, created_by=uploaded_by) for tag in set(data.get("tags", []))]
            )
            asset = AudioAsset.objects.create(
                id=asset_id,
                audio_content=content,
                asset_role=AudioAsset.AssetRole.ORIGINAL,
                storage_backend=settings.BM_AUDIO_STORAGE_ALIAS,
                storage_key=saved_key,
                original_filename=safe_filename,
                mime_type="audio/wav",
                container_format="wav",
                codec="pcm",
                bitrate_kbps=technical["bitrate_kbps"],
                sample_rate_hz=technical["sample_rate_hz"],
                channels=technical["channels"],
                size_bytes=uploaded_file.size,
                duration_ms=technical["duration_ms"],
                checksum_sha256=technical["checksum_sha256"],
                version=1,
                processing_status=AudioAsset.ProcessingStatus.READY,
                is_primary=True,
            )
            for job_type in (ProcessingJob.JobType.VALIDATE, ProcessingJob.JobType.PROBE, ProcessingJob.JobType.CHECKSUM):
                ProcessingJob.objects.create(
                    audio_asset=asset,
                    job_type=job_type,
                    status=ProcessingJob.Status.SUCCEEDED,
                    progress=100,
                    attempts=1,
                    queued_at=now,
                    started_at=now,
                    finished_at=now,
                    result={"validated": True},
                )
            upload_session = UploadSession.objects.create(
                uploaded_by=uploaded_by,
                owner_company=None,
                original_filename=safe_filename,
                storage_key=saved_key,
                size_bytes=uploaded_file.size,
                checksum_sha256=technical["checksum_sha256"],
                target_content_type=UploadSession.TargetContentType.SONG,
                status=UploadSession.Status.COMPLETED,
                created_audio_content=content,
                completed_at=now,
            )
            content.status = AudioContent.Status.READY
            content.published_at = now
            content.save(update_fields=["status", "published_at", "updated_at"])
    except IntegrityError as exc:
        if saved_key:
            storage.delete(saved_key)
        if AudioAsset.objects.filter(checksum_sha256=technical["checksum_sha256"]).exists():
            raise AudioAssetDuplicate() from exc
        raise AudioContentCodeConflict() from exc
    except Exception:
        if saved_key:
            try:
                storage.delete(saved_key)
            except Exception:
                pass
        raise

    return {
        "song_id": song.id,
        "audio_content_id": content.id,
        "audio_asset_id": asset.id,
        "upload_session_id": upload_session.id,
        "status": content.status,
        "duration_ms": content.duration_ms,
        "checksum_sha256": asset.checksum_sha256,
    }
