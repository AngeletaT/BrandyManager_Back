from pathlib import PurePosixPath

from django.conf import settings
from django.core.files.storage import storages
from django.http import HttpResponse, StreamingHttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.exceptions import AudioAssetUnavailable
from apps.catalog.internal_serializers import InternalSongIngestResultSerializer, InternalSongIngestSerializer
from apps.catalog.permissions import CanManageInternalCatalog
from apps.catalog.selectors import get_authorized_manifest_asset_for_device
from apps.catalog.services import ingest_global_song
from apps.devices.auth import DeviceJWTAuthentication
from apps.devices.models import DeviceEvent
from apps.devices.service_auth import HasGoServiceToken


def _safe_storage_key(value):
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    return bool(normalized and not path.is_absolute() and ".." not in path.parts)


def _parse_range(value, size):
    if not value:
        return 0, size - 1, False
    if not value.startswith("bytes=") or "," in value:
        return None
    spec = value[6:].strip()
    start_text, separator, end_text = spec.partition("-")
    if not separator:
        return None
    try:
        if not start_text:
            suffix = int(end_text)
            if suffix <= 0:
                return None
            start = max(0, size - suffix)
            end = size - 1
        else:
            start = int(start_text)
            end = int(end_text) if end_text else size - 1
    except ValueError:
        return None
    if start < 0 or end < start or start >= size:
        return None
    return start, min(end, size - 1), True


def _file_chunks(file_obj, *, remaining, chunk_size=64 * 1024):
    try:
        while remaining > 0:
            chunk = file_obj.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
    finally:
        file_obj.close()


class InternalSongIngestView(APIView):
    permission_classes = [IsAuthenticated, CanManageInternalCatalog]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        serializer = InternalSongIngestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = ingest_global_song(uploaded_by=request.user, data=serializer.validated_data)
        return Response(InternalSongIngestResultSerializer(result).data, status=status.HTTP_201_CREATED)


class InternalAudioAssetStreamView(APIView):
    authentication_classes = [DeviceJWTAuthentication]
    permission_classes = [IsAuthenticated, HasGoServiceToken]

    def get(self, request, asset_id):
        now = timezone.now()
        device = request.user.device
        manifest, item = get_authorized_manifest_asset_for_device(device=device, asset_id=asset_id, at=now)
        if not manifest or not item:
            raise AudioAssetUnavailable()

        asset = item.audio_asset
        if not _safe_storage_key(asset.storage_key):
            raise AudioAssetUnavailable()
        storage = storages[asset.storage_backend]
        if not storage.exists(asset.storage_key):
            raise AudioAssetUnavailable()

        etag = f'"{asset.checksum_sha256}"'
        if not request.headers.get("Range") and request.headers.get("If-None-Match") == etag:
            response = HttpResponse(status=status.HTTP_304_NOT_MODIFIED)
            response["ETag"] = etag
            return response

        range_header = request.headers.get("Range", "")
        if range_header and request.headers.get("If-Range") not in (None, "", etag):
            range_header = ""
        parsed_range = _parse_range(range_header, asset.size_bytes)
        if parsed_range is None:
            response = HttpResponse(status=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE)
            response["Content-Range"] = f"bytes */{asset.size_bytes}"
            response["Accept-Ranges"] = "bytes"
            return response
        start, end, is_partial = parsed_range

        try:
            file_obj = storage.open(asset.storage_key, "rb")
            file_obj.seek(start)
        except (OSError, ValueError):
            raise AudioAssetUnavailable()

        length = end - start + 1
        response = StreamingHttpResponse(
            _file_chunks(file_obj, remaining=length),
            status=status.HTTP_206_PARTIAL_CONTENT if is_partial else status.HTTP_200_OK,
            content_type=asset.mime_type,
        )
        response["Accept-Ranges"] = "bytes"
        response["Content-Length"] = str(length)
        response["ETag"] = etag
        response["X-Content-Type-Options"] = "nosniff"
        if is_partial:
            response["Content-Range"] = f"bytes {start}-{end}/{asset.size_bytes}"
        cache_seconds = max(0, min(settings.BM_AUDIO_CACHE_MAX_SECONDS, int((manifest.expires_at - now).total_seconds())))
        response["Cache-Control"] = f"private, max-age={cache_seconds}, immutable"

        DeviceEvent.objects.create(
            company=device.company,
            device=device,
            event_type="AUDIO_ASSET_ACCESSED",
            severity=DeviceEvent.Severity.INFO,
            occurred_at=now,
            payload={
                "audio_asset_id": str(asset.id),
                "manifest_id": str(manifest.id),
                "range_start": start,
                "range_end": end,
            },
            app_version=device.app_version,
        )
        return response
