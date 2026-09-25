from django.core.exceptions import ObjectDoesNotExist
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
from rest_framework import serializers

from apps.authorization.services import get_or_create_zone_scope, membership_has_permission
from apps.devices.models import Device, DeviceCommand, DeviceEvent


class DeviceStateSerializer(serializers.Serializer):
    playback_status = serializers.CharField()
    position_ms = serializers.IntegerField()
    volume = serializers.IntegerField()
    is_online = serializers.BooleanField()
    last_heartbeat_at = serializers.DateTimeField(allow_null=True)
    manifest_version = serializers.IntegerField(allow_null=True)
    schedule_version = serializers.IntegerField(allow_null=True)
    current_audio_content_id = serializers.UUIDField(allow_null=True)
    current_channel_id = serializers.UUIDField(allow_null=True)
    current_playlist_id = serializers.UUIDField(allow_null=True)
    current_audio_content = serializers.SerializerMethodField()
    current_channel = serializers.SerializerMethodField()
    current_playlist = serializers.SerializerMethodField()

    def get_current_audio_content(self, obj):
        if not obj.current_audio_content_id:
            return None
        return {"id": str(obj.current_audio_content_id), "title": obj.current_audio_content.title}

    def get_current_channel(self, obj):
        if not obj.current_channel_id:
            return None
        return {"id": str(obj.current_channel_id), "name": obj.current_channel.name}

    def get_current_playlist(self, obj):
        if not obj.current_playlist_id:
            return None
        return {"id": str(obj.current_playlist_id), "name": obj.current_playlist.name}


class DeviceSerializer(serializers.ModelSerializer):
    zone = serializers.SerializerMethodField()
    state = serializers.SerializerMethodField()
    permissions = serializers.SerializerMethodField()
    connectivity_status = serializers.SerializerMethodField()

    class Meta:
        model = Device
        fields = [
            "id",
            "code",
            "name",
            "device_type",
            "administrative_status",
            "activation_status",
            "connectivity_status",
            "configuration",
            "configuration_version",
            "zone",
            "state",
            "activated_at",
            "deactivated_at",
            "revoked_at",
            "archived_at",
            "last_seen_at",
            "last_sync_at",
            "created_at",
            "updated_at",
            "permissions",
        ]
        read_only_fields = fields

    def get_zone(self, obj):
        if not obj.zone_id:
            return None
        return {
            "id": str(obj.zone_id),
            "name": obj.zone.name,
            "site": {"id": str(obj.zone.site_id), "name": obj.zone.site.name},
        }

    def get_connectivity_status(self, obj):
        if not obj.last_seen_at:
            return Device.ConnectivityStatus.UNKNOWN
        threshold = timezone.now() - timedelta(seconds=settings.BM_DEVICE_OFFLINE_THRESHOLD_SECONDS)
        return Device.ConnectivityStatus.ONLINE if obj.last_seen_at >= threshold else Device.ConnectivityStatus.OFFLINE

    def get_state(self, obj):
        try:
            data = DeviceStateSerializer(obj.state).data
            threshold = timezone.now() - timedelta(seconds=settings.BM_DEVICE_OFFLINE_THRESHOLD_SECONDS)
            data["is_online"] = bool(obj.state.last_heartbeat_at and obj.state.last_heartbeat_at >= threshold)
            return data
        except ObjectDoesNotExist:
            return None

    def get_permissions(self, obj):
        membership = self.context.get("membership")
        if not membership or not obj.zone_id:
            return {
                "can_view": False,
                "can_update": False,
                "can_manage_activation": False,
                "can_send_commands": False,
                "can_change_volume": False,
            }
        scope = get_or_create_zone_scope(zone=obj.zone)
        is_archived = obj.administrative_status == Device.AdministrativeStatus.ARCHIVED
        return {
            "can_view": membership_has_permission(membership=membership, permission_code="devices.view", scope=scope),
            "can_update": not is_archived
            and membership_has_permission(membership=membership, permission_code="devices.manage", scope=scope),
            "can_manage_activation": not is_archived
            and membership_has_permission(membership=membership, permission_code="devices.manage", scope=scope),
            "can_send_commands": not is_archived
            and membership_has_permission(membership=membership, permission_code="playback.control", scope=scope),
            "can_change_volume": not is_archived
            and membership_has_permission(membership=membership, permission_code="playback.volume", scope=scope),
        }


class DeviceCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, trim_whitespace=True)
    code = serializers.CharField(max_length=80, trim_whitespace=True)
    zone_id = serializers.UUIDField()
    device_type = serializers.ChoiceField(choices=Device.DeviceType.choices, default=Device.DeviceType.DESKTOP_APP)
    configuration = serializers.JSONField(required=False, default=dict)


class DeviceUpdateSerializer(serializers.Serializer):
    expected_revision = serializers.IntegerField(min_value=1)
    name = serializers.CharField(max_length=255, required=False, trim_whitespace=True)
    code = serializers.CharField(max_length=80, required=False, trim_whitespace=True)
    device_type = serializers.ChoiceField(choices=Device.DeviceType.choices, required=False)
    configuration = serializers.JSONField(required=False)


class DeviceZoneUpdateSerializer(serializers.Serializer):
    expected_revision = serializers.IntegerField(min_value=1)
    zone_id = serializers.UUIDField()
    reason = serializers.CharField(max_length=1000, required=False, allow_blank=True)


class DeviceExpectedRevisionSerializer(serializers.Serializer):
    expected_revision = serializers.IntegerField(min_value=1)


class DeviceActivationCodeSerializer(serializers.Serializer):
    code = serializers.CharField(read_only=True)
    expires_at = serializers.DateTimeField(read_only=True)


class DeviceActivationValidateSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=32, trim_whitespace=True)


class DeviceActivationCompleteSerializer(DeviceActivationValidateSerializer):
    device_name = serializers.CharField(max_length=255, required=False, allow_blank=True, trim_whitespace=True)
    app_version = serializers.CharField(max_length=120, required=False, allow_blank=True, trim_whitespace=True)


class DeviceCommandCreateSerializer(serializers.Serializer):
    command_type = serializers.ChoiceField(
        choices=(
            DeviceCommand.CommandType.SET_VOLUME,
            DeviceCommand.CommandType.MUTE,
            DeviceCommand.CommandType.UNMUTE,
            DeviceCommand.CommandType.RESTART_PLAYBACK,
            DeviceCommand.CommandType.FORCE_SYNC,
            DeviceCommand.CommandType.ENABLE,
            DeviceCommand.CommandType.DISABLE,
        )
    )
    payload = serializers.JSONField(required=False, default=dict)
    idempotency_key = serializers.UUIDField(required=False)


class DeviceCommandSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeviceCommand
        fields = [
            "id",
            "device_id",
            "command_type",
            "payload",
            "status",
            "created_at",
            "expires_at",
            "delivered_at",
            "acknowledged_at",
            "executed_at",
            "result",
            "error_message",
        ]
        read_only_fields = fields


class DeviceEventSerializer(serializers.ModelSerializer):
    audio_asset_id = serializers.UUIDField(allow_null=True)
    manifest_id = serializers.UUIDField(allow_null=True)

    class Meta:
        model = DeviceEvent
        fields = [
            "id",
            "external_event_id",
            "sequence",
            "event_type",
            "severity",
            "occurred_at",
            "received_at",
            "manifest_id",
            "configuration_version",
            "audio_asset_id",
            "position_ms",
            "error_code",
            "payload",
            "app_version",
        ]
        read_only_fields = fields
