import io
import math
import struct
import tempfile
import wave
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase
from rest_framework_simplejwt.tokens import AccessToken

from apps.authorization.models import PlatformRole, UserPlatformRole
from apps.catalog.models import AudioAsset, AudioContent, Genre
from apps.devices.auth import issue_device_access_token
from apps.devices.models import Device, DeviceCredential, DeviceEvent
from apps.organizations.tests import factories as f
from apps.playback.models import ContentManifest, ZoneOperationalSnapshot
from apps.playback.services import create_manifest


def synthetic_wav(*, frequency=440, duration_ms=120, sample_rate=8000):
    buffer = io.BytesIO()
    frame_count = sample_rate * duration_ms // 1000
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        for index in range(frame_count):
            sample = int(10000 * math.sin(2 * math.pi * frequency * index / sample_rate))
            wav_file.writeframesraw(struct.pack("<h", sample))
    return buffer.getvalue()


@override_settings(BM_GO_SERVICE_TOKEN="service-token")
class Phase4AudioDeliveryTests(APITestCase):
    def setUp(self):
        call_command("seed_initial_data", verbosity=0)
        self.media_dir = tempfile.TemporaryDirectory()
        self.settings_override = override_settings(MEDIA_ROOT=self.media_dir.name)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.addCleanup(self.media_dir.cleanup)

        self.genre = Genre.objects.get(slug="ambient")
        self.internal_user = f.user("content-manager@example.com")
        self.internal_user.email_verified_at = timezone.now()
        self.internal_user.save(update_fields=["email_verified_at"])
        role = PlatformRole.objects.get(code="CONTENT_MANAGER")
        UserPlatformRole.objects.create(user=self.internal_user, role=role)

    def upload_payload(self, *, code="SYNTH-001", content=None, content_type="audio/wav"):
        return {
            "file": SimpleUploadedFile("tone.wav", content or synthetic_wav(), content_type=content_type),
            "title": "Tono sintetico",
            "internal_code": code,
            "genre_id": str(self.genre.id),
            "rights_holder": "BrandyManager test suite",
            "rights_reference": "SYNTHETIC-TEST-ONLY",
        }

    def ingest(self, **payload_overrides):
        self.client.force_authenticate(self.internal_user)
        payload = self.upload_payload()
        payload.update(payload_overrides)
        return self.client.post(reverse("internal-catalog-song-ingest"), payload, format="multipart")

    def test_only_platform_content_manager_can_ingest_song(self):
        response = self.ingest()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        content = AudioContent.objects.get(id=response.data["audio_content_id"])
        asset = AudioAsset.objects.get(id=response.data["audio_asset_id"])
        self.assertEqual(content.status, AudioContent.Status.READY)
        self.assertEqual(content.rights_verified_by, self.internal_user)
        self.assertEqual(asset.mime_type, "audio/wav")
        self.assertGreater(asset.duration_ms, 0)

        client_user = f.user("company-owner@example.com")
        self.client.force_authenticate(client_user)
        denied = self.client.post(
            reverse("internal-catalog-song-ingest"),
            self.upload_payload(code="DENIED-CLIENT"),
            format="multipart",
        )
        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN)

        staff_without_role = f.user("staff-only@example.com")
        staff_without_role.is_staff = True
        staff_without_role.save(update_fields=["is_staff"])
        self.client.force_authenticate(staff_without_role)
        staff_denied = self.client.post(
            reverse("internal-catalog-song-ingest"),
            self.upload_payload(code="DENIED-STAFF"),
            format="multipart",
        )
        self.assertEqual(staff_denied.status_code, status.HTTP_403_FORBIDDEN)

    def test_invalid_fake_mime_and_duplicate_files_are_rejected(self):
        invalid = self.ingest(
            internal_code="INVALID",
            file=SimpleUploadedFile("fake.wav", b"not a wave", content_type="audio/wav"),
        )
        self.assertEqual(invalid.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(invalid.data["error"]["code"], "audio_file_invalid")

        false_mime = self.ingest(
            internal_code="FALSE-MIME",
            file=SimpleUploadedFile("tone.mp3", synthetic_wav(), content_type="audio/mpeg"),
        )
        self.assertEqual(false_mime.status_code, status.HTTP_400_BAD_REQUEST)

        first = self.ingest(internal_code="DUPLICATE-ONE")
        second = self.ingest(internal_code="DUPLICATE-TWO")
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(second.data["error"]["code"], "audio_asset_duplicate")

    def create_player_context(self):
        upload = self.ingest()
        asset = AudioAsset.objects.get(id=upload.data["audio_asset_id"])
        company = f.company("audio-player")
        site = f.site(company, "audio-site")
        zone = f.zone(company, site, "audio-zone")
        device = Device.objects.create(
            company=company,
            zone=zone,
            hardware_id="audio-hardware",
            code="AUDIO-PLAYER",
            name="Audio player",
            device_type=Device.DeviceType.DESKTOP_APP,
            administrative_status=Device.AdministrativeStatus.ACTIVE,
            activation_status=Device.ActivationStatus.ACTIVATED,
        )
        credential = DeviceCredential.objects.create(
            device=device,
            credential_id="audio-credential",
            secret_hash="not-a-plain-secret",
            status=DeviceCredential.Status.ACTIVE,
            expires_at=timezone.now() + timedelta(days=1),
        )
        snapshot = ZoneOperationalSnapshot.objects.create(
            company=company,
            zone=zone,
            version=1,
            status=ZoneOperationalSnapshot.Status.READY,
            checksum="snapshot-checksum",
            generated_at=timezone.now(),
            snapshot_data={
                "execution_observed": False,
                "assets": [{"audio_asset_id": str(asset.id), "asset_available": True}],
            },
        )
        manifest = create_manifest(
            zone=zone,
            operational_snapshot=snapshot,
            expires_at=timezone.now() + timedelta(hours=1),
        )
        access, _ = issue_device_access_token(device=device, credential=credential)
        return asset, device, manifest, access

    def stream(self, *, asset, access, range_header=None):
        client = APIClient()
        headers = {
            "HTTP_AUTHORIZATION": f"Bearer {access}",
            "HTTP_X_BRANDYMANAGER_SERVICE_TOKEN": "service-token",
        }
        if range_header:
            headers["HTTP_RANGE"] = range_header
        return client.get(reverse("internal-audio-asset-stream", kwargs={"asset_id": asset.id}), **headers)

    def test_authorized_audio_supports_full_and_range_responses(self):
        asset, _, _, access = self.create_player_context()
        full = self.stream(asset=asset, access=access)
        self.assertEqual(full.status_code, status.HTTP_200_OK)
        full_body = b"".join(full.streaming_content)
        self.assertTrue(full_body.startswith(b"RIFF"))
        self.assertEqual(int(full["Content-Length"]), len(full_body))
        self.assertEqual(full["Content-Type"], "audio/wav")
        self.assertEqual(full["ETag"], f'"{asset.checksum_sha256}"')

        partial = self.stream(asset=asset, access=access, range_header="bytes=0-11")
        self.assertEqual(partial.status_code, status.HTTP_206_PARTIAL_CONTENT)
        self.assertEqual(b"".join(partial.streaming_content), full_body[:12])
        self.assertEqual(partial["Content-Range"], f"bytes 0-11/{asset.size_bytes}")
        self.assertEqual(partial["Accept-Ranges"], "bytes")
        self.assertTrue(DeviceEvent.objects.filter(event_type="AUDIO_ASSET_ACCESSED").exists())

    def test_audio_denies_expired_manifest_unavailable_asset_and_other_device(self):
        asset, device, manifest, access = self.create_player_context()
        manifest.expires_at = timezone.now() - timedelta(seconds=1)
        manifest.save(update_fields=["expires_at"])
        expired = self.stream(asset=asset, access=access)
        self.assertEqual(expired.status_code, status.HTTP_404_NOT_FOUND)

        manifest.expires_at = timezone.now() + timedelta(hours=1)
        manifest.save(update_fields=["expires_at"])
        asset.processing_status = AudioAsset.ProcessingStatus.ERROR
        asset.save(update_fields=["processing_status"])
        unavailable = self.stream(asset=asset, access=access)
        self.assertEqual(unavailable.status_code, status.HTTP_404_NOT_FOUND)

        asset.processing_status = AudioAsset.ProcessingStatus.READY
        asset.save(update_fields=["processing_status"])
        content = asset.audio_content
        verified_at = content.rights_verified_at
        content.rights_verified_at = None
        content.save(update_fields=["rights_verified_at"])
        rights_revoked = self.stream(asset=asset, access=access)
        self.assertEqual(rights_revoked.status_code, status.HTTP_404_NOT_FOUND)
        content.rights_verified_at = verified_at
        content.save(update_fields=["rights_verified_at"])

        other_company = f.company("other-audio-company")
        other_site = f.site(other_company, "other-audio-site")
        other_device = Device.objects.create(
            company=other_company,
            zone=f.zone(other_company, other_site, "other-audio-zone"),
            hardware_id="other-audio-hardware",
            code="OTHER-AUDIO",
            name="Other audio player",
            device_type=Device.DeviceType.DESKTOP_APP,
            activation_status=Device.ActivationStatus.ACTIVATED,
        )
        other_credential = DeviceCredential.objects.create(
            device=other_device,
            credential_id="other-audio-credential",
            secret_hash="hash",
            expires_at=timezone.now() + timedelta(days=1),
        )
        other_access, _ = issue_device_access_token(device=other_device, credential=other_credential)
        denied = self.stream(asset=asset, access=other_access)
        self.assertEqual(denied.status_code, status.HTTP_404_NOT_FOUND)

    def test_revoked_device_and_user_token_cannot_download_audio(self):
        asset, device, _, access = self.create_player_context()
        device.activation_status = Device.ActivationStatus.REVOKED
        device.revoked_at = timezone.now()
        device.save(update_fields=["activation_status", "revoked_at"])
        revoked = self.stream(asset=asset, access=access)
        self.assertEqual(revoked.status_code, status.HTTP_401_UNAUTHORIZED)

        user_access = str(AccessToken.for_user(self.internal_user))
        wrong_audience = self.stream(asset=asset, access=user_access)
        self.assertEqual(wrong_audience.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_service_token_is_required_and_storage_key_is_not_exposed(self):
        asset, _, _, access = self.create_player_context()
        client = APIClient()
        response = client.get(
            reverse("internal-audio-asset-stream", kwargs={"asset_id": asset.id}),
            HTTP_AUTHORIZATION=f"Bearer {access}",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertNotContains(response, asset.storage_key, status_code=status.HTTP_403_FORBIDDEN)
