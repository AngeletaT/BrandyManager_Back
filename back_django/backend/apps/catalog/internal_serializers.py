from rest_framework import serializers

from apps.catalog.models import Genre, Tag


class InternalSongIngestSerializer(serializers.Serializer):
    file = serializers.FileField()
    title = serializers.CharField(max_length=255, trim_whitespace=True)
    internal_code = serializers.CharField(max_length=120, trim_whitespace=True)
    description = serializers.CharField(required=False, allow_blank=True, trim_whitespace=True)
    genre_id = serializers.PrimaryKeyRelatedField(source="genre", queryset=Genre.objects.filter(is_active=True))
    tag_ids = serializers.PrimaryKeyRelatedField(
        source="tags",
        queryset=Tag.objects.filter(is_active=True, category__is_active=True),
        many=True,
        required=False,
    )
    rights_holder = serializers.CharField(max_length=255, trim_whitespace=True)
    rights_reference = serializers.CharField(max_length=255, trim_whitespace=True)
    is_explicit = serializers.BooleanField(required=False, default=False)
    generation_provider = serializers.CharField(max_length=120, required=False, allow_blank=True, trim_whitespace=True)
    generation_model = serializers.CharField(max_length=120, required=False, allow_blank=True, trim_whitespace=True)
    generation_reference = serializers.CharField(max_length=255, required=False, allow_blank=True, trim_whitespace=True)


class InternalSongIngestResultSerializer(serializers.Serializer):
    song_id = serializers.UUIDField()
    audio_content_id = serializers.UUIDField()
    audio_asset_id = serializers.UUIDField()
    upload_session_id = serializers.UUIDField()
    status = serializers.CharField()
    duration_ms = serializers.IntegerField()
    checksum_sha256 = serializers.CharField()
