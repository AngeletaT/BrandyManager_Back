from rest_framework import serializers

from apps.devices.models import DeviceCommand, DeviceState


class PlayerTelemetryEventSerializer(serializers.Serializer):
    class EventType:
        VALUES = (
            "HEARTBEAT",
            "MANIFEST_LOADED",
            "PLAYBACK_STARTED",
            "PLAYBACK_PROGRESS",
            "PLAYBACK_COMPLETED",
            "PLAYBACK_ERROR",
            "OFFLINE",
            "ONLINE",
            "COMMAND_ACKNOWLEDGED",
        )

    event_id = serializers.UUIDField()
    sequence = serializers.IntegerField(min_value=1)
    occurred_at = serializers.DateTimeField()
    manifest_id = serializers.UUIDField(required=False, allow_null=True)
    configuration_version = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    asset_id = serializers.UUIDField(required=False, allow_null=True)
    event_type = serializers.ChoiceField(choices=EventType.VALUES)
    position_ms = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    playback_status = serializers.ChoiceField(
        choices=DeviceState.PlaybackStatus.choices,
        required=False,
    )
    volume = serializers.IntegerField(required=False, min_value=0, max_value=100)
    error_code = serializers.CharField(required=False, allow_blank=True, max_length=80)
    app_version = serializers.CharField(required=False, allow_blank=True, max_length=120)
    technical = serializers.JSONField(required=False)

    def validate_technical(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Debe ser un objeto JSON.")
        if len(str(value)) > 4096:
            raise serializers.ValidationError("Los datos tecnicos son demasiado grandes.")
        return value


class PlayerTelemetryBatchSerializer(serializers.Serializer):
    events = PlayerTelemetryEventSerializer(many=True, allow_empty=False)

    def validate_events(self, value):
        if len(value) > 100:
            raise serializers.ValidationError("Se admiten como maximo 100 eventos por lote.")
        return value


class PlayerCommandAckSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=(
            DeviceCommand.Status.ACKNOWLEDGED,
            DeviceCommand.Status.EXECUTED,
            DeviceCommand.Status.FAILED,
        )
    )
    result = serializers.JSONField(required=False)
    error_message = serializers.CharField(required=False, allow_blank=True, max_length=2000)

