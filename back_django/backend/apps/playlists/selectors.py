from uuid import UUID

from django.db.models import Count, Q, Sum

from apps.authorization.services import get_company_scope, membership_has_permission, site_ids_accessible_by_membership, zone_ids_accessible_by_membership
from apps.organizations.models import ResourceScope, ZoneChannelAssignment
from apps.playlists.models import Channel, ChannelSnapshot, ContentAccessGrant, Playlist, PlaylistSnapshot
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

CHANNEL_ORDERING_FIELDS = {
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


def accessible_channel_base_queryset(*, company):
    shared_channel_ids = ContentAccessGrant.objects.filter(
        company=company,
        channel__isnull=False,
        revoked_at__isnull=True,
    ).values("channel_id")

    return (
        Channel.objects.filter(
            Q(owner_company=company)
            | Q(owner_company__isnull=True, visibility=Channel.Visibility.GLOBAL, status=Channel.Status.PUBLISHED)
            | Q(visibility=Channel.Visibility.SHARED, id__in=shared_channel_ids)
        )
        .select_related("owner_company")
        .prefetch_related("channel_playlists__playlist", "channel_playlists__playlist__snapshots", "policy", "snapshots")
        .distinct()
    )


def list_accessible_channels(
    *,
    membership,
    permission_code="channels.view",
    search="",
    status_value="",
    visibility="",
    ordering="name",
):
    company = membership.company
    queryset = accessible_channel_base_queryset(company=company).annotate(
        assigned_zone_count=Count(
            "zone_assignments",
            filter=Q(zone_assignments__unassigned_at__isnull=True),
            distinct=True,
        )
    )

    company_scope = get_company_scope(company=company)
    if not membership_has_permission(membership=membership, permission_code=permission_code, scope=company_scope):
        zone_ids = zone_ids_accessible_by_membership(membership=membership, permission_code=permission_code)
        site_ids = site_ids_accessible_by_membership(membership=membership, permission_code=permission_code)
        scope_filter = Q(zone_assignments__unassigned_at__isnull=True, zone_assignments__zone_id__in=zone_ids)
        if site_ids:
            scope_filter |= Q(zone_assignments__unassigned_at__isnull=True, zone_assignments__zone__site_id__in=site_ids)
        queryset = queryset.filter(scope_filter)

    search = (search or "").strip()
    if search:
        queryset = queryset.filter(Q(name__icontains=search) | Q(code__icontains=search) | Q(description__icontains=search))
    status_value = (status_value or "").strip()
    if status_value:
        queryset = queryset.filter(status=status_value)
    visibility = (visibility or "").strip()
    if visibility:
        queryset = queryset.filter(visibility=visibility)
    return queryset.order_by(CHANNEL_ORDERING_FIELDS.get(ordering, "name"), "id").distinct()


def get_accessible_channel_by_id(*, membership, channel_id, permission_code="channels.view"):
    channel_uuid = _as_uuid(channel_id)
    if not channel_uuid:
        return None
    return list_accessible_channels(membership=membership, permission_code=permission_code).filter(id=channel_uuid).first()


def get_owned_channel_by_id(*, company, channel_id):
    channel_uuid = _as_uuid(channel_id)
    if not channel_uuid:
        return None
    return (
        Channel.objects.filter(id=channel_uuid, owner_company=company)
        .select_related("owner_company")
        .prefetch_related("channel_playlists__playlist", "channel_playlists__playlist__snapshots", "policy", "snapshots")
        .first()
    )


def get_latest_published_channel_snapshot(*, channel):
    return (
        ChannelSnapshot.objects.filter(channel=channel, status=ChannelSnapshot.Status.PUBLISHED)
        .prefetch_related("playlists__playlist", "playlists__playlist_snapshot")
        .order_by("-version", "-created_at")
        .first()
    )


def count_billable_channels(*, company):
    return Channel.objects.filter(owner_company=company).exclude(status=Channel.Status.ARCHIVED).count()


def list_active_channel_zone_assignments(*, channel):
    return (
        ZoneChannelAssignment.objects.filter(channel=channel, unassigned_at__isnull=True)
        .select_related("zone", "zone__site", "channel")
        .order_by("zone__site__name", "zone__name", "id")
    )


def list_channel_zone_assignments_for_membership(*, channel, membership, permission_code="channels.view"):
    queryset = list_active_channel_zone_assignments(channel=channel)
    company_scope = get_company_scope(company=membership.company)
    if membership_has_permission(membership=membership, permission_code=permission_code, scope=company_scope):
        return queryset
    zone_ids = zone_ids_accessible_by_membership(membership=membership, permission_code=permission_code)
    site_ids = site_ids_accessible_by_membership(membership=membership, permission_code=permission_code)
    scope_filter = Q(zone_id__in=zone_ids)
    if site_ids:
        scope_filter |= Q(zone__site_id__in=site_ids)
    return queryset.filter(scope_filter)


def get_active_zone_channel_assignment(*, zone):
    return (
        ZoneChannelAssignment.objects.filter(zone=zone, unassigned_at__isnull=True)
        .select_related("channel", "zone", "zone__site")
        .first()
    )


def get_zone_channel_assignment_for_membership(*, zone, membership, permission_code="channels.view"):
    zone_scope = ResourceScope.objects.filter(
        company=membership.company,
        scope_type=ResourceScope.ScopeType.ZONE,
        zone=zone,
    ).first()
    if not zone_scope or not membership_has_permission(membership=membership, permission_code=permission_code, scope=zone_scope):
        return None
    return get_active_zone_channel_assignment(zone=zone)
