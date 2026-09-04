from rest_framework import serializers

from apps.authorization.services import membership_has_permission_on_any_scope
from apps.playlists.models import Playlist
from apps.playlists.selectors import calculate_playlist_duration_ms, get_latest_published_snapshot, list_playlist_usages


class PlaylistSongGenreSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    slug = serializers.SlugField()


class PlaylistSongSummarySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    title = serializers.CharField(source="audio_content.title")
    genre = PlaylistSongGenreSerializer()
    duration_ms = serializers.IntegerField(source="audio_content.duration_ms", allow_null=True)
    duration_unit = serializers.SerializerMethodField()
    is_explicit = serializers.BooleanField()

    def get_duration_unit(self, obj):
        return "milliseconds"


class PlaylistItemSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    position = serializers.IntegerField()
    weight = serializers.IntegerField()
    song = PlaylistSongSummarySerializer()
    active_from = serializers.DateTimeField(allow_null=True)
    active_until = serializers.DateTimeField(allow_null=True)


class PlaylistSnapshotSummarySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    version = serializers.IntegerField()
    status = serializers.CharField()
    checksum = serializers.CharField()
    published_at = serializers.DateTimeField(allow_null=True)
    item_count = serializers.SerializerMethodField()

    def get_item_count(self, obj):
        return obj.items.count()


class PlaylistUsageSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    schedule = serializers.SerializerMethodField()
    day_of_week = serializers.IntegerField()
    start_time = serializers.TimeField()
    end_time = serializers.TimeField()
    content_type = serializers.CharField()
    priority = serializers.IntegerField()

    def get_schedule(self, obj):
        return {
            "id": str(obj.schedule_id),
            "name": obj.schedule.name,
            "status": obj.schedule.status,
            "version": obj.schedule.version,
        }


class PlaylistListSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    code = serializers.CharField()
    description = serializers.CharField()
    playlist_type = serializers.CharField()
    visibility = serializers.CharField()
    status = serializers.CharField()
    current_version = serializers.IntegerField()
    revision = serializers.IntegerField()
    song_count = serializers.SerializerMethodField()
    duration_ms = serializers.SerializerMethodField()
    duration_unit = serializers.SerializerMethodField()
    published_at = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
    permissions = serializers.SerializerMethodField()

    def get_song_count(self, obj):
        return obj.items.count()

    def get_duration_ms(self, obj):
        return calculate_playlist_duration_ms(playlist=obj)

    def get_duration_unit(self, obj):
        return "milliseconds"

    def get_permissions(self, obj):
        membership = self.context.get("membership")
        can_manage = bool(
            membership
            and obj.owner_company_id == membership.company_id
            and membership_has_permission_on_any_scope(membership=membership, permission_code="playlists.manage")
        )
        is_archived = obj.status == Playlist.Status.ARCHIVED
        return {
            "can_view": True,
            "can_update": can_manage and not is_archived,
            "can_archive": can_manage and not is_archived,
            "can_reactivate": can_manage and is_archived,
            "can_publish": can_manage and not is_archived,
            "can_duplicate": bool(
                membership
                and membership_has_permission_on_any_scope(membership=membership, permission_code="playlists.manage")
            ),
        }


class PlaylistDetailSerializer(PlaylistListSerializer):
    items = serializers.SerializerMethodField()
    latest_snapshot = serializers.SerializerMethodField()
    usage = serializers.SerializerMethodField()

    def get_items(self, obj):
        return PlaylistItemSerializer(obj.items.order_by("position", "id"), many=True).data

    def get_latest_snapshot(self, obj):
        snapshot = get_latest_published_snapshot(playlist=obj)
        if not snapshot:
            return None
        return PlaylistSnapshotSummarySerializer(snapshot).data

    def get_usage(self, obj):
        return PlaylistUsageSerializer(list_playlist_usages(playlist=obj), many=True).data


class PlaylistCreateSerializer(serializers.Serializer):
    FORBIDDEN_FIELDS = {
        "id",
        "owner_company",
        "company",
        "company_id",
        "status",
        "current_version",
        "revision",
        "visibility",
        "created_by",
        "published_at",
        "archived_at",
    }

    name = serializers.CharField(max_length=255)
    code = serializers.CharField(max_length=120, required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        forbidden = sorted(set(self.initial_data) & self.FORBIDDEN_FIELDS)
        if forbidden:
            raise serializers.ValidationError(
                {field: ["Este campo no puede enviarse desde este endpoint."] for field in forbidden}
            )
        for field, value in list(attrs.items()):
            if isinstance(value, str):
                attrs[field] = value.strip()
        return attrs


class PlaylistUpdateSerializer(PlaylistCreateSerializer):
    name = serializers.CharField(max_length=255, required=False)
    expected_revision = serializers.IntegerField(min_value=1)


class PlaylistExpectedRevisionSerializer(serializers.Serializer):
    expected_revision = serializers.IntegerField(min_value=1)


class PlaylistAddItemSerializer(PlaylistExpectedRevisionSerializer):
    song_id = serializers.UUIDField()
    weight = serializers.IntegerField(min_value=1, required=False, default=1)


class PlaylistReplaceItemSerializer(serializers.Serializer):
    song_id = serializers.UUIDField()
    position = serializers.IntegerField(min_value=1)
    weight = serializers.IntegerField(min_value=1, required=False, default=1)


class PlaylistReplaceItemsSerializer(PlaylistExpectedRevisionSerializer):
    items = serializers.ListField(child=PlaylistReplaceItemSerializer(), allow_empty=True)

    def validate(self, attrs):
        positions = [item["position"] for item in attrs.get("items", [])]
        if len(positions) != len(set(positions)):
            raise serializers.ValidationError({"items": ["No puede haber posiciones duplicadas."]})
        if positions and sorted(positions) != list(range(1, len(positions) + 1)):
            raise serializers.ValidationError({"items": ["Las posiciones deben ser consecutivas desde 1."]})
        return attrs


class PlaylistReorderItemsSerializer(PlaylistExpectedRevisionSerializer):
    item_ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=False)

    def validate(self, attrs):
        item_ids = attrs.get("item_ids", [])
        if len(item_ids) != len(set(item_ids)):
            raise serializers.ValidationError({"item_ids": ["No puede haber elementos duplicados."]})
        return attrs


class PlaylistDuplicateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    code = serializers.CharField(max_length=120, required=False, allow_blank=True)

    def validate(self, attrs):
        for field, value in list(attrs.items()):
            if isinstance(value, str):
                attrs[field] = value.strip()
        return attrs
