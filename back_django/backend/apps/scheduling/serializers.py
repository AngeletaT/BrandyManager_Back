from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from rest_framework import serializers

from apps.authorization.services import membership_has_permission_on_any_scope
from apps.organizations.models import ResourceScope
from apps.playlists.serializers import PlaylistSnapshotSummarySerializer
from apps.playlists.selectors import get_latest_published_snapshot
from apps.scheduling.models import Schedule, ScheduleAssignment, ScheduleBlock, ScheduleException
from apps.scheduling.selectors import list_next_occurrences


class ScheduleScopeSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    scope_type = serializers.CharField()
    name = serializers.CharField()
    site = serializers.SerializerMethodField()
    zone = serializers.SerializerMethodField()

    def get_site(self, obj):
        if not obj.site_id:
            return None
        return {"id": str(obj.site_id), "name": obj.site.name}

    def get_zone(self, obj):
        if not obj.zone_id:
            return None
        return {"id": str(obj.zone_id), "name": obj.zone.name}


class SchedulePlaylistSummarySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    status = serializers.CharField()
    current_version = serializers.IntegerField()
    published_snapshot = serializers.SerializerMethodField()

    def get_published_snapshot(self, obj):
        snapshot = get_latest_published_snapshot(playlist=obj)
        return PlaylistSnapshotSummarySerializer(snapshot).data if snapshot else None


class ScheduleBlockSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    day_of_week = serializers.IntegerField()
    start_time = serializers.TimeField()
    end_time = serializers.TimeField()
    content_type = serializers.CharField()
    playlist = SchedulePlaylistSummarySerializer(allow_null=True)
    channel = serializers.SerializerMethodField()
    priority = serializers.IntegerField()
    volume_override = serializers.IntegerField(allow_null=True)
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()

    def get_channel(self, obj):
        return None


class ScheduleExceptionSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    date = serializers.DateField()
    start_time = serializers.TimeField()
    end_time = serializers.TimeField()
    action = serializers.CharField()
    playlist = SchedulePlaylistSummarySerializer(allow_null=True)
    channel = serializers.SerializerMethodField()
    priority = serializers.IntegerField()
    volume_override = serializers.IntegerField(allow_null=True)
    description = serializers.CharField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()

    def get_channel(self, obj):
        return None


class ScheduleAssignmentSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    scope = ScheduleScopeSerializer()
    priority = serializers.IntegerField()
    is_locked = serializers.BooleanField()
    starts_at = serializers.DateTimeField(allow_null=True)
    ends_at = serializers.DateTimeField(allow_null=True)
    is_active = serializers.BooleanField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()


class ScheduleListSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    description = serializers.CharField()
    timezone = serializers.CharField()
    status = serializers.CharField()
    valid_from = serializers.DateField(allow_null=True)
    valid_until = serializers.DateField(allow_null=True)
    version = serializers.IntegerField()
    revision = serializers.IntegerField()
    block_count = serializers.SerializerMethodField()
    assignment_count = serializers.SerializerMethodField()
    published_at = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
    permissions = serializers.SerializerMethodField()

    def get_block_count(self, obj):
        return getattr(obj, "block_count", obj.blocks.count())

    def get_assignment_count(self, obj):
        return getattr(obj, "assignment_count", obj.assignments.count())

    def get_permissions(self, obj):
        membership = self.context.get("membership")
        can_manage = bool(
            membership
            and membership_has_permission_on_any_scope(membership=membership, permission_code="schedules.manage")
        )
        is_archived = obj.status == Schedule.Status.ARCHIVED
        return {
            "can_view": True,
            "can_update": can_manage and not is_archived,
            "can_archive": can_manage and not is_archived,
            "can_reactivate": can_manage and is_archived,
            "can_publish": can_manage and not is_archived,
            "can_disable": can_manage and obj.status == Schedule.Status.PUBLISHED,
        }


class ScheduleDetailSerializer(ScheduleListSerializer):
    blocks = serializers.SerializerMethodField()
    exceptions = serializers.SerializerMethodField()
    assignments = serializers.SerializerMethodField()

    def get_blocks(self, obj):
        return ScheduleBlockSerializer(obj.blocks.select_related("playlist").order_by("day_of_week", "start_time", "-priority", "id"), many=True).data

    def get_exceptions(self, obj):
        return ScheduleExceptionSerializer(obj.exceptions.select_related("playlist").order_by("date", "start_time", "-priority", "id"), many=True).data

    def get_assignments(self, obj):
        return ScheduleAssignmentSerializer(obj.assignments.select_related("scope", "scope__site", "scope__zone").order_by("-is_active", "-priority", "id"), many=True).data


class ScheduleWriteSerializer(serializers.Serializer):
    FORBIDDEN_FIELDS = {"id", "company", "company_id", "status", "version", "revision", "created_by", "published_at"}

    name = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, allow_blank=True)
    timezone = serializers.CharField(max_length=64)
    valid_from = serializers.DateField(required=False, allow_null=True)
    valid_until = serializers.DateField(required=False, allow_null=True)

    def validate_timezone(self, value):
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise serializers.ValidationError("Zona horaria no valida.") from exc
        return value

    def validate(self, attrs):
        forbidden = sorted(set(self.initial_data) & self.FORBIDDEN_FIELDS)
        if forbidden:
            raise serializers.ValidationError({field: ["Este campo no puede enviarse desde este endpoint."] for field in forbidden})
        for field, value in list(attrs.items()):
            if isinstance(value, str):
                attrs[field] = value.strip()
        if attrs.get("valid_from") and attrs.get("valid_until") and attrs["valid_until"] < attrs["valid_from"]:
            raise serializers.ValidationError({"valid_until": ["Debe ser posterior o igual a valid_from."]})
        return attrs


class ScheduleUpdateSerializer(ScheduleWriteSerializer):
    name = serializers.CharField(max_length=255, required=False)
    timezone = serializers.CharField(max_length=64, required=False)
    expected_revision = serializers.IntegerField(min_value=1)


class ScheduleExpectedRevisionSerializer(serializers.Serializer):
    expected_revision = serializers.IntegerField(min_value=1)


class ScheduleBlockWriteSerializer(ScheduleExpectedRevisionSerializer):
    FORBIDDEN_FIELDS = {"id", "schedule", "schedule_id", "channel", "channel_id", "created_at", "updated_at"}

    day_of_week = serializers.IntegerField(min_value=0, max_value=6)
    start_time = serializers.TimeField()
    end_time = serializers.TimeField()
    content_type = serializers.ChoiceField(choices=[ScheduleBlock.ContentType.PLAYLIST, ScheduleBlock.ContentType.SILENCE])
    playlist_id = serializers.UUIDField(required=False, allow_null=True)
    priority = serializers.IntegerField(required=False, default=0)
    volume_override = serializers.IntegerField(min_value=0, max_value=100, required=False, allow_null=True)

    def validate(self, attrs):
        forbidden = sorted(set(self.initial_data) & self.FORBIDDEN_FIELDS)
        if forbidden:
            raise serializers.ValidationError({field: ["Este campo no puede enviarse desde este endpoint."] for field in forbidden})
        if attrs["start_time"] >= attrs["end_time"]:
            raise serializers.ValidationError({"end_time": ["Los bloques que cruzan medianoche deben dividirse en dos registros."]})
        if attrs["content_type"] == ScheduleBlock.ContentType.PLAYLIST and not attrs.get("playlist_id"):
            raise serializers.ValidationError({"playlist_id": ["La playlist es obligatoria para bloques PLAYLIST."]})
        if attrs["content_type"] == ScheduleBlock.ContentType.SILENCE and attrs.get("playlist_id"):
            raise serializers.ValidationError({"playlist_id": ["SILENCE no acepta playlist."]})
        return attrs


class ScheduleBlockUpdateSerializer(ScheduleBlockWriteSerializer):
    day_of_week = serializers.IntegerField(min_value=0, max_value=6, required=False)
    start_time = serializers.TimeField(required=False)
    end_time = serializers.TimeField(required=False)
    content_type = serializers.ChoiceField(choices=[ScheduleBlock.ContentType.PLAYLIST, ScheduleBlock.ContentType.SILENCE], required=False)

    def validate(self, attrs):
        forbidden = sorted(set(self.initial_data) & self.FORBIDDEN_FIELDS)
        if forbidden:
            raise serializers.ValidationError({field: ["Este campo no puede enviarse desde este endpoint."] for field in forbidden})
        if "start_time" in attrs and "end_time" in attrs and attrs["start_time"] >= attrs["end_time"]:
            raise serializers.ValidationError({"end_time": ["Los bloques que cruzan medianoche deben dividirse en dos registros."]})
        if attrs.get("content_type") == ScheduleBlock.ContentType.SILENCE and attrs.get("playlist_id"):
            raise serializers.ValidationError({"playlist_id": ["SILENCE no acepta playlist."]})
        return attrs


class ScheduleExceptionWriteSerializer(ScheduleExpectedRevisionSerializer):
    FORBIDDEN_FIELDS = {"id", "schedule", "schedule_id", "channel", "channel_id", "created_at", "updated_at"}

    date = serializers.DateField()
    start_time = serializers.TimeField()
    end_time = serializers.TimeField()
    action = serializers.ChoiceField(choices=[ScheduleException.Action.REPLACE, ScheduleException.Action.SILENCE, ScheduleException.Action.VOLUME_OVERRIDE])
    playlist_id = serializers.UUIDField(required=False, allow_null=True)
    priority = serializers.IntegerField(required=False, default=0)
    volume_override = serializers.IntegerField(min_value=0, max_value=100, required=False, allow_null=True)
    description = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        forbidden = sorted(set(self.initial_data) & self.FORBIDDEN_FIELDS)
        if forbidden:
            raise serializers.ValidationError({field: ["Este campo no puede enviarse desde este endpoint."] for field in forbidden})
        if attrs["start_time"] >= attrs["end_time"]:
            raise serializers.ValidationError({"end_time": ["Las excepciones que cruzan medianoche deben dividirse en dos registros."]})
        if attrs["action"] == ScheduleException.Action.REPLACE and not attrs.get("playlist_id"):
            raise serializers.ValidationError({"playlist_id": ["La playlist es obligatoria para excepciones REPLACE."]})
        if attrs["action"] == ScheduleException.Action.SILENCE and attrs.get("playlist_id"):
            raise serializers.ValidationError({"playlist_id": ["SILENCE no acepta playlist."]})
        if attrs["action"] == ScheduleException.Action.VOLUME_OVERRIDE and attrs.get("volume_override") is None:
            raise serializers.ValidationError({"volume_override": ["El volumen es obligatorio para VOLUME_OVERRIDE."]})
        return attrs


class ScheduleExceptionUpdateSerializer(ScheduleExceptionWriteSerializer):
    date = serializers.DateField(required=False)
    start_time = serializers.TimeField(required=False)
    end_time = serializers.TimeField(required=False)
    action = serializers.ChoiceField(choices=[ScheduleException.Action.REPLACE, ScheduleException.Action.SILENCE, ScheduleException.Action.VOLUME_OVERRIDE], required=False)

    def validate(self, attrs):
        forbidden = sorted(set(self.initial_data) & self.FORBIDDEN_FIELDS)
        if forbidden:
            raise serializers.ValidationError({field: ["Este campo no puede enviarse desde este endpoint."] for field in forbidden})
        if "start_time" in attrs and "end_time" in attrs and attrs["start_time"] >= attrs["end_time"]:
            raise serializers.ValidationError({"end_time": ["Las excepciones que cruzan medianoche deben dividirse en dos registros."]})
        return attrs


class ScheduleAssignmentWriteSerializer(ScheduleExpectedRevisionSerializer):
    FORBIDDEN_FIELDS = {"id", "company", "company_id", "schedule", "schedule_id", "scope", "scope_id", "created_at", "updated_at"}

    scope_type = serializers.ChoiceField(choices=[ResourceScope.ScopeType.COMPANY, ResourceScope.ScopeType.SITE, ResourceScope.ScopeType.ZONE])
    site_id = serializers.UUIDField(required=False, allow_null=True)
    zone_id = serializers.UUIDField(required=False, allow_null=True)
    priority = serializers.IntegerField(required=False, default=0)
    is_locked = serializers.BooleanField(required=False, default=False)
    starts_at = serializers.DateTimeField(required=False, allow_null=True)
    ends_at = serializers.DateTimeField(required=False, allow_null=True)
    is_active = serializers.BooleanField(required=False, default=True)

    def validate(self, attrs):
        forbidden = sorted(set(self.initial_data) & self.FORBIDDEN_FIELDS)
        if forbidden:
            raise serializers.ValidationError({field: ["Este campo no puede enviarse desde este endpoint."] for field in forbidden})
        if attrs.get("starts_at") and attrs.get("ends_at") and attrs["ends_at"] <= attrs["starts_at"]:
            raise serializers.ValidationError({"ends_at": ["Debe ser posterior a starts_at."]})
        return attrs


class ScheduleAssignmentUpdateSerializer(ScheduleExpectedRevisionSerializer):
    FORBIDDEN_FIELDS = ScheduleAssignmentWriteSerializer.FORBIDDEN_FIELDS | {"scope_type", "site_id", "zone_id"}

    priority = serializers.IntegerField(required=False)
    is_locked = serializers.BooleanField(required=False)
    starts_at = serializers.DateTimeField(required=False, allow_null=True)
    ends_at = serializers.DateTimeField(required=False, allow_null=True)
    is_active = serializers.BooleanField(required=False)

    def validate(self, attrs):
        forbidden = sorted(set(self.initial_data) & self.FORBIDDEN_FIELDS)
        if forbidden:
            raise serializers.ValidationError({field: ["Este campo no puede enviarse desde este endpoint."] for field in forbidden})
        if attrs.get("starts_at") and attrs.get("ends_at") and attrs["ends_at"] <= attrs["starts_at"]:
            raise serializers.ValidationError({"ends_at": ["Debe ser posterior a starts_at."]})
        return attrs


class ScheduleOccurrenceQuerySerializer(serializers.Serializer):
    start_at = serializers.DateTimeField(required=False)
    days = serializers.IntegerField(min_value=1, max_value=90, required=False, default=14)
    limit = serializers.IntegerField(min_value=1, max_value=100, required=False, default=20)


class ScheduleResolveQuerySerializer(serializers.Serializer):
    zone_id = serializers.UUIDField()
    at = serializers.DateTimeField(required=False)


def serialize_occurrence(occurrence):
    obj = occurrence["block"] or occurrence["exception"]
    playlist = getattr(obj, "playlist", None)
    return {
        "kind": occurrence["kind"],
        "starts_at": occurrence["starts_at"],
        "ends_at": occurrence["ends_at"],
        "content_type": getattr(obj, "content_type", getattr(obj, "action", None)),
        "playlist": SchedulePlaylistSummarySerializer(playlist).data if playlist else None,
        "priority": obj.priority,
        "source_id": str(obj.id),
    }


def schedule_occurrences_response(*, schedule, start_at, days, limit):
    return {
        "schedule_id": str(schedule.id),
        "calculation_type": "configuration_preview",
        "execution_observed": False,
        "results": [
            serialize_occurrence(occurrence)
            for occurrence in list_next_occurrences(schedule=schedule, start_at=start_at, days=days, limit=limit)
        ],
    }
