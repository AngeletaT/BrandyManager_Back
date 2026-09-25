import hashlib

from django.conf import settings
from django.core.cache import cache
from rest_framework.exceptions import Throttled
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.devices.auth import DeviceJWTAuthentication
from apps.devices.internal_serializers import PlayerCommandAckSerializer, PlayerTelemetryBatchSerializer
from apps.devices.service_auth import HasGoServiceToken
from apps.devices.services import acknowledge_device_command, deliver_device_commands, record_device_telemetry
from apps.playback.services import get_or_create_player_runtime


def _request_id(request):
    return request.headers.get("X-Request-ID", "")[:120]


def _enforce_telemetry_rate_limit(request):
    digest = hashlib.sha256(str(request.user.device.id).encode("ascii")).hexdigest()
    key = f"player-telemetry:{digest}"
    if cache.add(key, 1, timeout=60):
        return
    attempts = cache.incr(key)
    if attempts > settings.BM_PLAYER_TELEMETRY_RATE_LIMIT:
        raise Throttled(detail="Demasiados lotes de telemetria.")


class InternalPlayerView(APIView):
    authentication_classes = [DeviceJWTAuthentication]
    permission_classes = [IsAuthenticated, HasGoServiceToken]


class InternalPlayerRuntimeView(InternalPlayerView):
    def get(self, request):
        return Response(get_or_create_player_runtime(device=request.user.device))

    def post(self, request):
        return Response(get_or_create_player_runtime(device=request.user.device, force_refresh=True))


class InternalPlayerTelemetryView(InternalPlayerView):
    def post(self, request):
        _enforce_telemetry_rate_limit(request)
        serializer = PlayerTelemetryBatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = record_device_telemetry(
            device=request.user.device,
            events=serializer.validated_data["events"],
            request_id=_request_id(request),
        )
        return Response(result)


class InternalPlayerCommandsView(InternalPlayerView):
    def get(self, request):
        commands = deliver_device_commands(device=request.user.device)
        return Response(
            {
                "commands": [
                    {
                        "command_id": str(command.id),
                        "type": command.command_type.lower(),
                        "payload": command.payload,
                        "issued_at": command.created_at,
                        "expires_at": command.expires_at,
                        "status": command.status,
                    }
                    for command in commands
                ]
            }
        )


class InternalPlayerCommandAckView(InternalPlayerView):
    def post(self, request, command_id):
        serializer = PlayerCommandAckSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        command = acknowledge_device_command(
            device=request.user.device,
            command_id=command_id,
            status=serializer.validated_data["status"],
            result=serializer.validated_data.get("result", {}),
            error_message=serializer.validated_data.get("error_message", ""),
        )
        return Response({"command_id": str(command.id), "status": command.status})
