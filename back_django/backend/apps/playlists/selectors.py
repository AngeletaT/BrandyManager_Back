from uuid import UUID

from django.db.models import Count, Q, Sum

from apps.playlists.models import ContentAccessGrant, Playlist, PlaylistSnapshot
from apps.scheduling.models import ScheduleBlock


PLAYLIST_ORDERING_FIELDS = {
    "name": "name",
    "-name": "-name",
    "created_at": "created_at",
    "-created_at": "-created_at",
    "updated_at": "updated_at",
    "-updated_at": "-updated_at",
    "published_at": "published_at",
    "-published_at": "-published_at",
}


def _as_uuid(value):
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def accessible_playlist_base_queryset(*, company):
    shared_playlist_ids = ContentAccessGrant.objects.filter(
        company=company,
        playlist__isnull=False,
        revoked_at__isnull=True,
    ).values("playlist_id")

    return (
        Playlist.objects.filter(
            Q(owner_company=company)
            | Q(owner_company__isnull=True, visibility=Playlist.Visibility.GLOBAL, status=Playlist.Status.PUBLISHED)
            | Q(visibility=Playlist.Visibility.SHARED, id__in=shared_playlist_ids)
        )
        .select_related("owner_company")
        .prefetch_related("items__song__audio_content", "items__song__genre", "items__song__song_tags__tag__category")
        .distinct()
    )


def list_accessible_playlists(*, company, search="", status_value="", visibility="", ordering="name"):
    queryset = accessible_playlist_base_queryset(company=company)

    search = (search or "").strip()
    if search:
        queryset = queryset.filter(Q(name__icontains=search) | Q(code__icontains=search) | Q(description__icontains=search))

    status_value = (status_value or "").strip()
    if status_value:
        queryset = queryset.filter(status=status_value)

    visibility = (visibility or "").strip()
    if visibility:
        queryset = queryset.filter(visibility=visibility)

    return queryset.order_by(PLAYLIST_ORDERING_FIELDS.get(ordering, "name"), "id")


def get_accessible_playlist_by_id(*, company, playlist_id):
    return accessible_playlist_base_queryset(company=company).filter(id=playlist_id).first()


def get_owned_playlist_by_id(*, company, playlist_id):
    return (
        Playlist.objects.select_related("owner_company")
        .prefetch_related("items__song__audio_content", "items__song__genre", "items__song__song_tags__tag__category")
        .filter(id=playlist_id, owner_company=company)
        .first()
    )


def get_latest_published_snapshot(*, playlist):
    return (
        PlaylistSnapshot.objects.filter(playlist=playlist, status=PlaylistSnapshot.Status.PUBLISHED)
        .order_by("-version", "-created_at")
        .first()
    )


def list_playlist_usages(*, playlist):
    return (
        ScheduleBlock.objects.filter(playlist=playlist)
        .select_related("schedule")
        .order_by("schedule__name", "day_of_week", "start_time", "id")
    )


def playlist_has_schedule_usage(*, playlist):
    return ScheduleBlock.objects.filter(playlist=playlist).exists()


def count_billable_playlists(*, company):
    return Playlist.objects.filter(owner_company=company).exclude(status=Playlist.Status.ARCHIVED).count()


def calculate_playlist_duration_ms(*, playlist):
    aggregate = playlist.items.aggregate(
        total=Sum("song__audio_content__duration_ms"),
        known=Count("song__audio_content__duration_ms"),
        total_items=Count("id"),
    )
    if aggregate["total_items"] and aggregate["known"] != aggregate["total_items"]:
        return None
    return aggregate["total"] or 0


def get_playlist_item(*, playlist, item_id):
    item_uuid = _as_uuid(item_id)
    if not item_uuid:
        return None
    return playlist.items.filter(id=item_uuid).select_related("song", "song__audio_content", "song__genre").first()
