from uuid import UUID

from django.db.models import Q

from apps.catalog.models import AudioAsset, AudioContent, Genre, Song, Tag
from apps.playlists.models import ContentAccessGrant


SONG_ORDERING_FIELDS = {
    "title": "audio_content__title",
    "-title": "-audio_content__title",
    "created_at": "audio_content__created_at",
    "-created_at": "-audio_content__created_at",
    "published_at": "audio_content__published_at",
    "-published_at": "-audio_content__published_at",
    "duration_ms": "audio_content__duration_ms",
    "-duration_ms": "-audio_content__duration_ms",
}


def _as_uuid(value):
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def accessible_song_base_queryset(*, company):
    shared_content_ids = ContentAccessGrant.objects.filter(
        company=company,
        audio_content__isnull=False,
        revoked_at__isnull=True,
    ).values("audio_content_id")

    return (
        Song.objects.select_related("audio_content", "genre")
        .prefetch_related("song_tags__tag__category")
        .filter(
            audio_content__content_type=AudioContent.ContentType.SONG,
            audio_content__status=AudioContent.Status.READY,
            audio_content__is_active=True,
        )
        .filter(
            Q(
                audio_content__visibility=AudioContent.Visibility.GLOBAL,
                audio_content__owner_company__isnull=True,
            )
            | Q(
                audio_content__visibility=AudioContent.Visibility.PRIVATE,
                audio_content__owner_company=company,
            )
            | Q(
                audio_content__visibility=AudioContent.Visibility.SHARED,
                audio_content__owner_company=company,
            )
            | Q(
                audio_content__visibility=AudioContent.Visibility.SHARED,
                audio_content_id__in=shared_content_ids,
            )
        )
        .distinct()
    )


def list_accessible_songs(
    *,
    company,
    search="",
    genre="",
    tags="",
    status_value="",
    ordering="title",
):
    queryset = accessible_song_base_queryset(company=company)

    if status_value and status_value != AudioContent.Status.READY:
        return queryset.none()

    search = (search or "").strip()
    if search:
        queryset = queryset.filter(
            Q(audio_content__title__icontains=search)
            | Q(audio_content__description__icontains=search)
            | Q(genre__name__icontains=search)
            | Q(genre__slug__icontains=search)
            | Q(song_tags__tag__name__icontains=search)
            | Q(song_tags__tag__slug__icontains=search)
        )

    genre = (genre or "").strip()
    if genre:
        genre_uuid = _as_uuid(genre)
        genre_filter = Q(genre__slug__iexact=genre)
        if genre_uuid:
            genre_filter |= Q(genre_id=genre_uuid)
        queryset = queryset.filter(genre_filter)

    tag_values = [value.strip() for value in (tags or "").split(",") if value.strip()]
    for tag_value in tag_values:
        tag_uuid = _as_uuid(tag_value)
        tag_filter = Q(song_tags__tag__slug__iexact=tag_value)
        if tag_uuid:
            tag_filter |= Q(song_tags__tag_id=tag_uuid)
        queryset = queryset.filter(tag_filter)

    return queryset.order_by(SONG_ORDERING_FIELDS.get(ordering, "audio_content__title"), "id").distinct()


def get_accessible_song_by_id(*, company, song_id):
    return accessible_song_base_queryset(company=company).filter(id=song_id).first()


def list_available_genres_for_company(*, company):
    accessible_song_ids = accessible_song_base_queryset(company=company).values("id")
    return (
        Genre.objects.filter(is_active=True, songs__id__in=accessible_song_ids)
        .distinct()
        .order_by("sort_order", "name", "id")
    )


def list_available_tags_for_company(*, company, category="", search=""):
    accessible_song_ids = accessible_song_base_queryset(company=company).values("id")
    queryset = (
        Tag.objects.select_related("category")
        .filter(is_active=True, category__is_active=True, song_tags__song_id__in=accessible_song_ids)
        .distinct()
    )

    category = (category or "").strip()
    if category:
        queryset = queryset.filter(category__code__iexact=category)

    search = (search or "").strip()
    if search:
        queryset = queryset.filter(Q(name__icontains=search) | Q(slug__icontains=search))

    return queryset.order_by("category__sort_order", "sort_order", "name", "id")


def list_available_assets_for_song(*, song):
    return song.audio_content.assets.filter(
        asset_role=AudioAsset.AssetRole.PREVIEW,
        processing_status=AudioAsset.ProcessingStatus.READY,
    ).order_by("version", "id")
