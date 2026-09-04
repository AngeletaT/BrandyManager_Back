from rest_framework import serializers

from apps.authorization.services import membership_has_permission_on_any_scope
from apps.catalog.selectors import list_available_assets_for_song


class GenreSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    slug = serializers.SlugField()
    description = serializers.CharField()
    sort_order = serializers.IntegerField()


class TagCategorySummarySerializer(serializers.Serializer):
    code = serializers.CharField()
    name = serializers.CharField()


class TagSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    category = TagCategorySummarySerializer()
    name = serializers.CharField()
    slug = serializers.SlugField()
    description = serializers.CharField()


class SongGenreSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    slug = serializers.SlugField()


class SongTagSerializer(serializers.Serializer):
    id = serializers.UUIDField(source="tag.id")
    category_code = serializers.CharField(source="tag.category.code")
    name = serializers.CharField(source="tag.name")
    slug = serializers.SlugField(source="tag.slug")


class AudioAssetSummarySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    asset_role = serializers.CharField()
    mime_type = serializers.CharField()
    duration_ms = serializers.IntegerField(allow_null=True)
    duration_unit = serializers.SerializerMethodField()
    processing_status = serializers.CharField()

    def get_duration_unit(self, obj):
        return "milliseconds"


class SongListSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    audio_content_id = serializers.UUIDField(source="audio_content.id")
    title = serializers.CharField(source="audio_content.title")
    description = serializers.CharField(source="audio_content.description")
    genre = SongGenreSerializer()
    tags = serializers.SerializerMethodField()
    duration_ms = serializers.IntegerField(source="audio_content.duration_ms", allow_null=True)
    duration_unit = serializers.SerializerMethodField()
    is_explicit = serializers.BooleanField()
    visibility = serializers.CharField(source="audio_content.visibility")
    status = serializers.CharField(source="audio_content.status")
    published_at = serializers.DateTimeField(source="audio_content.published_at", allow_null=True)
    permissions = serializers.SerializerMethodField()

    def get_tags(self, obj):
        song_tags = obj.song_tags.all()
        return SongTagSerializer(song_tags, many=True).data

    def get_duration_unit(self, obj):
        return "milliseconds"

    def get_permissions(self, obj):
        membership = self.context.get("membership")
        can_add_to_playlist = bool(
            membership
            and membership_has_permission_on_any_scope(
                membership=membership,
                permission_code="playlists.manage",
            )
        )
        return {
            "can_view": True,
            "can_use": True,
            "can_add_to_playlist": can_add_to_playlist,
        }


class SongDetailSerializer(SongListSerializer):
    assets = serializers.SerializerMethodField()

    def get_assets(self, obj):
        return AudioAssetSummarySerializer(list_available_assets_for_song(song=obj), many=True).data
