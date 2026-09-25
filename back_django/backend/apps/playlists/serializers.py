from rest_framework import serializers

from apps.authorization.services import membership_has_permission_on_any_scope
from apps.playback.models import ZoneOperationalSnapshot
from apps.playlists.models import Channel, ChannelPolicy, Playlist
from apps.playlists.selectors import (
    calculate_playlist_duration_ms,
    get_latest_published_channel_snapshot,
    get_latest_published_snapshot,
    list_active_channel_zone_assignments,
    list_playlist_usages,
)


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


class ChannelPolicySerializer(serializers.Serializer):
    order_mode = serializers.CharField()
    repeat_song_gap_count = serializers.IntegerField()
    max_same_genre_in_row = serializers.IntegerField()
    avoid_same_tag_in_row = serializers.BooleanField()
    crossfade_ms = serializers.IntegerField()
    fade_in_ms = serializers.IntegerField()
    fade_out_ms = serializers.IntegerField()
    normalize_loudness = serializers.BooleanField()
    target_lufs = serializers.DecimalField(max_digits=5, decimal_places=2, allow_null=True)
    settings = serializers.JSONField()


class ChannelPlaylistSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    playlist = serializers.SerializerMethodField()
    weight = serializers.IntegerField()
    priority = serializers.IntegerField()
    active_from = serializers.DateTimeField(allow_null=True)
    active_until = serializers.DateTimeField(allow_null=True)

    def get_playlist(self, obj):
        snapshot = get_latest_published_snapshot(playlist=obj.playlist)
        return {
            "id": str(obj.playlist_id),
            "name": obj.playlist.name,
            "code": obj.playlist.code,
            "status": obj.playlist.status,
            "current_version": obj.playlist.current_version,
            "latest_snapshot": PlaylistSnapshotSummarySerializer(snapshot).data if snapshot else None,
        }


class ChannelSnapshotPlaylistSerializer(serializers.Serializer):
    playlist = serializers.SerializerMethodField()
    playlist_snapshot = PlaylistSnapshotSummarySerializer()
    weight = serializers.IntegerField()
    priority = serializers.IntegerField()
    active_from = serializers.DateTimeField(allow_null=True)
    active_until = serializers.DateTimeField(allow_null=True)

    def get_playlist(self, obj):
        return {
            "id": str(obj.playlist_id),
            "name": obj.playlist.name,
            "code": obj.playlist.code,
            "status": obj.playlist.status,
        }


class ChannelSnapshotSummarySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    version = serializers.IntegerField()
    status = serializers.CharField()
    checksum = serializers.CharField()
    published_at = serializers.DateTimeField(allow_null=True)
    playlist_count = serializers.SerializerMethodField()

    def get_playlist_count(self, obj):
        return obj.playlists.count()


class ChannelSnapshotDetailSerializer(ChannelSnapshotSummarySerializer):
    policy_snapshot = serializers.JSONField()
    playlists = ChannelSnapshotPlaylistSerializer(many=True)


class ChannelZoneAssignmentSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    zone = serializers.SerializerMethodField()
    channel = serializers.SerializerMethodField()
    assigned_at = serializers.DateTimeField()
    reason = serializers.CharField()

    def get_zone(self, obj):
        return {
            "id": str(obj.zone_id),
            "name": obj.zone.name,
            "code": obj.zone.code,
            "status": obj.zone.status,
            "site": {"id": str(obj.zone.site_id), "name": obj.zone.site.name},
        }

    def get_channel(self, obj):
        return {
            "id": str(obj.channel_id),
            "name": obj.channel.name,
            "code": obj.channel.code,
            "status": obj.channel.status,
            "current_version": obj.channel.current_version,
        }


class ZoneOperationalSnapshotSummarySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    version = serializers.IntegerField()
    status = serializers.CharField()
    checksum = serializers.CharField()
    generated_at = serializers.DateTimeField()
    reason = serializers.CharField()
    execution_observed = serializers.SerializerMethodField()

    def get_execution_observed(self, obj):
        return obj.snapshot_data.get("execution_observed", False)


class ChannelListSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    code = serializers.CharField()
    description = serializers.CharField()
    visibility = serializers.CharField()
    status = serializers.CharField()
    current_version = serializers.IntegerField()
    revision = serializers.IntegerField()
    assigned_zone_count = serializers.SerializerMethodField()
    published_at = serializers.DateTimeField(allow_null=True)
    archived_at = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
    permissions = serializers.SerializerMethodField()

    def get_assigned_zone_count(self, obj):
        return getattr(obj, "assigned_zone_count", None) or list_active_channel_zone_assignments(channel=obj).count()

    def get_permissions(self, obj):
        membership = self.context.get("membership")
        can_manage = bool(
            membership
            and obj.owner_company_id == membership.company_id
            and membership_has_permission_on_any_scope(membership=membership, permission_code="channels.manage")
        )
        can_select = bool(
            membership
            and membership_has_permission_on_any_scope(membership=membership, permission_code="channels.select")
        )
        is_archived = obj.status == Channel.Status.ARCHIVED
        return {
            "can_view": True,
            "can_update": can_manage and not is_archived,
            "can_archive": can_manage and not is_archived,
            "can_reactivate": can_manage and is_archived,
            "can_publish": can_manage and not is_archived,
            "can_duplicate": can_manage,
            "can_assign": can_select and not is_archived and obj.status == Channel.Status.PUBLISHED,
        }


class ChannelDetailSerializer(ChannelListSerializer):
    policy = serializers.SerializerMethodField()
    playlists = serializers.SerializerMethodField()
    latest_snapshot = serializers.SerializerMethodField()
    assigned_zones = serializers.SerializerMethodField()
    operational_configuration = serializers.SerializerMethodField()

    def get_policy(self, obj):
        try:
            policy = obj.policy
        except ChannelPolicy.DoesNotExist:
            return {
                "order_mode": ChannelPolicy.OrderMode.SHUFFLE,
                "repeat_song_gap_count": 10,
                "max_same_genre_in_row": 3,
                "avoid_same_tag_in_row": True,
                "crossfade_ms": 0,
                "fade_in_ms": 0,
                "fade_out_ms": 0,
                "normalize_loudness": True,
                "target_lufs": None,
                "settings": {},
            }
        return ChannelPolicySerializer(policy).data

    def get_playlists(self, obj):
        return ChannelPlaylistSerializer(obj.channel_playlists.select_related("playlist").order_by("-priority", "playlist__name", "id"), many=True).data

    def get_latest_snapshot(self, obj):
        snapshot = get_latest_published_channel_snapshot(channel=obj)
        return ChannelSnapshotSummarySerializer(snapshot).data if snapshot else None

    def get_assigned_zones(self, obj):
        return ChannelZoneAssignmentSerializer(list_active_channel_zone_assignments(channel=obj), many=True).data

    def get_operational_configuration(self, obj):
        snapshots = ZoneOperationalSnapshot.objects.filter(channel=obj).order_by("-generated_at")[:5]
        return {
            "published": obj.current_version > 0,
            "channel_version": obj.current_version,
            "recent_zone_snapshots": ZoneOperationalSnapshotSummarySerializer(snapshots, many=True).data,
        }


class ChannelCreateSerializer(serializers.Serializer):
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


class ChannelUpdateSerializer(ChannelCreateSerializer):
    name = serializers.CharField(max_length=255, required=False)
    expected_revision = serializers.IntegerField(min_value=1)


class ChannelExpectedRevisionSerializer(serializers.Serializer):
    expected_revision = serializers.IntegerField(min_value=1)


class ChannelDuplicateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    code = serializers.CharField(max_length=120, required=False, allow_blank=True)

    def validate(self, attrs):
        for field, value in list(attrs.items()):
            if isinstance(value, str):
                attrs[field] = value.strip()
        return attrs


class ChannelPolicyUpdateSerializer(ChannelExpectedRevisionSerializer):
    order_mode = serializers.ChoiceField(choices=ChannelPolicy.OrderMode.choices, required=False)
    repeat_song_gap_count = serializers.IntegerField(min_value=0, required=False)
    max_same_genre_in_row = serializers.IntegerField(min_value=1, required=False)
    avoid_same_tag_in_row = serializers.BooleanField(required=False)
    crossfade_ms = serializers.IntegerField(min_value=0, required=False)
    fade_in_ms = serializers.IntegerField(min_value=0, required=False)
    fade_out_ms = serializers.IntegerField(min_value=0, required=False)
    normalize_loudness = serializers.BooleanField(required=False)
    target_lufs = serializers.DecimalField(max_digits=5, decimal_places=2, required=False, allow_null=True)
    settings = serializers.JSONField(required=False)


class ChannelPlaylistWriteSerializer(serializers.Serializer):
    playlist_id = serializers.UUIDField()
    weight = serializers.IntegerField(min_value=1, required=False, default=1)
    priority = serializers.IntegerField(required=False, default=0)
    active_from = serializers.DateTimeField(required=False, allow_null=True)
    active_until = serializers.DateTimeField(required=False, allow_null=True)

    def validate(self, attrs):
        active_from = attrs.get("active_from")
        active_until = attrs.get("active_until")
        if active_from and active_until and active_until <= active_from:
            raise serializers.ValidationError({"active_until": ["Debe ser posterior a active_from."]})
        return attrs


class ChannelReplacePlaylistsSerializer(ChannelExpectedRevisionSerializer):
    playlists = serializers.ListField(child=ChannelPlaylistWriteSerializer(), allow_empty=True)

    def validate(self, attrs):
        playlist_ids = [item["playlist_id"] for item in attrs.get("playlists", [])]
        if len(playlist_ids) != len(set(playlist_ids)):
            raise serializers.ValidationError({"playlists": ["No puede haber playlists duplicadas."]})
        return attrs


class AssignChannelToZoneSerializer(serializers.Serializer):
    channel_id = serializers.UUIDField()
    reason = serializers.CharField(required=False, allow_blank=True)


class UnassignChannelFromZoneSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True)
