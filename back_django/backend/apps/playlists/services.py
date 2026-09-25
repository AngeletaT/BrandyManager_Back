import hashlib
import json

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.billing.selectors import get_current_subscription_for_company
from apps.catalog.selectors import get_accessible_song_by_id
from apps.organizations.models import Company, Site, Zone, ZoneChannelAssignment
from apps.playlists.exceptions import (
    ChannelCodeConflict,
    ChannelInUse,
    ChannelLimitReached,
    ChannelNotPublishable,
    ChannelPlaylistInvalid,
    ChannelRevisionConflict,
    PlaylistCodeConflict,
    PlaylistContentUnavailable,
    PlaylistInUse,
    PlaylistLimitReached,
    PlaylistNotPublishable,
    PlaylistOrderConflict,
    PlaylistRevisionConflict,
    ZoneChannelAssignmentInvalid,
)
from apps.playlists.models import (
    Channel,
    ChannelPlaylist,
    ChannelPolicy,
    ChannelSnapshot,
    ChannelSnapshotPlaylist,
    Playlist,
    PlaylistItem,
    PlaylistSnapshot,
    PlaylistSnapshotItem,
)
from apps.playlists.selectors import (
    count_billable_channels,
    count_billable_playlists,
    get_accessible_playlist_by_id,
    get_latest_published_channel_snapshot,
    get_latest_published_snapshot,
    playlist_has_schedule_usage,
)


def normalize_playlist_code(value):
    value = (value or "").strip()
    return slugify(value).upper()[:120]


def code_from_name(name):
    return normalize_playlist_code(name) or "PLAYLIST"


def next_available_code(*, company, base_code):
    base_code = normalize_playlist_code(base_code) or "PLAYLIST"
    code = base_code
    suffix = 2
    while Playlist.objects.filter(owner_company=company, code=code).exists():
        tail = f"-{suffix}"
        code = f"{base_code[:120 - len(tail)]}{tail}"
        suffix += 1
    return code


def normalize_channel_code(value):
    value = (value or "").strip()
    return slugify(value).upper()[:120]


def next_available_channel_code(*, company, base_code):
    base_code = normalize_channel_code(base_code) or "CHANNEL"
    code = base_code
    suffix = 2
    while Channel.objects.filter(owner_company=company, code=code).exists():
        tail = f"-{suffix}"
        code = f"{base_code[:120 - len(tail)]}{tail}"
        suffix += 1
    return code


def playlist_checksum(*, playlist):
    source = "|".join(
        f"{item.song_id}:{item.position}:{item.weight}"
        for item in playlist.items.select_related("song").order_by("position", "id")
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def assert_expected_revision(*, playlist, expected_revision):
    if playlist.revision != expected_revision:
        raise PlaylistRevisionConflict()


def assert_expected_channel_revision(*, channel, expected_revision):
    if channel.revision != expected_revision:
        raise ChannelRevisionConflict()


def assert_playlist_limit(*, company):
    subscription = get_current_subscription_for_company(company=company)
    limits = subscription.effective_limits() if subscription else {}
    limit = limits.get("playlists")
    if limit is not None and count_billable_playlists(company=company) >= limit:
        raise PlaylistLimitReached()


def assert_channel_limit(*, company):
    subscription = get_current_subscription_for_company(company=company)
    limits = subscription.effective_limits() if subscription else {}
    limit = limits.get("channels")
    if limit is not None and count_billable_channels(company=company) >= limit:
        raise ChannelLimitReached()


def assert_song_available(*, company, song_id):
    song = get_accessible_song_by_id(company=company, song_id=song_id)
    if not song:
        raise PlaylistContentUnavailable()
    return song


def assert_all_playlist_songs_available(*, company, playlist):
    for item in playlist.items.select_related("song").order_by("position", "id"):
        if not get_accessible_song_by_id(company=company, song_id=item.song_id):
            raise PlaylistNotPublishable(fields={"items": ["La playlist contiene canciones no disponibles."]})


def bump_revision(*, playlist, update_fields):
    playlist.revision += 1
    update_fields = list(update_fields)
    if "revision" not in update_fields:
        update_fields.append("revision")
    if "updated_at" not in update_fields:
        update_fields.append("updated_at")
    playlist.save(update_fields=update_fields)
    return playlist


def bump_channel_revision(*, channel, update_fields):
    channel.revision += 1
    update_fields = list(update_fields)
    if "revision" not in update_fields:
        update_fields.append("revision")
    if "updated_at" not in update_fields:
        update_fields.append("updated_at")
    channel.save(update_fields=update_fields)
    return channel


def channel_policy_snapshot(*, channel):
    policy, _ = ChannelPolicy.objects.get_or_create(channel=channel)
    return {
        "order_mode": policy.order_mode,
        "repeat_song_gap_count": policy.repeat_song_gap_count,
        "max_same_genre_in_row": policy.max_same_genre_in_row,
        "avoid_same_tag_in_row": policy.avoid_same_tag_in_row,
        "crossfade_ms": policy.crossfade_ms,
        "fade_in_ms": policy.fade_in_ms,
        "fade_out_ms": policy.fade_out_ms,
        "normalize_loudness": policy.normalize_loudness,
        "target_lufs": str(policy.target_lufs) if policy.target_lufs is not None else None,
        "settings": policy.settings,
    }


def channel_snapshot_payload(*, channel):
    playlists = []
    for relation in channel.channel_playlists.select_related("playlist").order_by("-priority", "playlist__name", "id"):
        playlist_snapshot = get_latest_published_snapshot(playlist=relation.playlist)
        playlists.append(
            {
                "playlist_id": str(relation.playlist_id),
                "playlist_snapshot_id": str(playlist_snapshot.id) if playlist_snapshot else None,
                "playlist_snapshot_version": playlist_snapshot.version if playlist_snapshot else None,
                "weight": relation.weight,
                "priority": relation.priority,
                "active_from": relation.active_from.isoformat() if relation.active_from else None,
                "active_until": relation.active_until.isoformat() if relation.active_until else None,
            }
        )
    return {
        "channel_id": str(channel.id),
        "name": channel.name,
        "code": channel.code,
        "policy": channel_policy_snapshot(channel=channel),
        "playlists": playlists,
    }


def channel_checksum(*, channel):
    payload = channel_snapshot_payload(channel=channel)
    source = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def assert_playlist_channel_available(*, company, playlist_id):
    playlist = get_accessible_playlist_by_id(company=company, playlist_id=playlist_id)
    if not playlist:
        raise ChannelPlaylistInvalid(fields={"playlist_id": ["La playlist no esta disponible para esta empresa."]})
    if playlist.status != Playlist.Status.PUBLISHED or not get_latest_published_snapshot(playlist=playlist):
        raise ChannelPlaylistInvalid(fields={"playlist_id": ["La playlist debe estar publicada para usarse en un canal."]})
    return playlist


def assert_channel_publishable(*, company, channel):
    if not channel.channel_playlists.exists():
        raise ChannelNotPublishable(fields={"playlists": ["El canal necesita al menos una playlist publicada."]})
    for relation in channel.channel_playlists.select_related("playlist"):
        playlist = assert_playlist_channel_available(company=company, playlist_id=relation.playlist_id)
        if playlist.status == Playlist.Status.ARCHIVED:
            raise ChannelNotPublishable(fields={"playlists": ["El canal contiene playlists archivadas."]})


@transaction.atomic
def create_playlist(*, company, data, actor):
    Company.objects.select_for_update().get(id=company.id)
    assert_playlist_limit(company=company)
    code = next_available_code(company=company, base_code=data.get("code") or data["name"])
    try:
        return Playlist.objects.create(
            owner_company=company,
            name=data["name"],
            code=code,
            description=data.get("description", ""),
            playlist_type=Playlist.PlaylistType.MANUAL,
            visibility=Playlist.Visibility.PRIVATE,
            status=Playlist.Status.DRAFT,
            created_by=actor,
        )
    except IntegrityError as exc:
        raise PlaylistCodeConflict() from exc


@transaction.atomic
def create_channel(*, company, data, actor):
    Company.objects.select_for_update().get(id=company.id)
    assert_channel_limit(company=company)
    code = next_available_channel_code(company=company, base_code=data.get("code") or data["name"])
    try:
        channel = Channel.objects.create(
            owner_company=company,
            name=data["name"],
            code=code,
            description=data.get("description", ""),
            visibility=Channel.Visibility.PRIVATE,
            status=Channel.Status.DRAFT,
            created_by=actor,
        )
        ChannelPolicy.objects.create(channel=channel)
        return channel
    except IntegrityError as exc:
        raise ChannelCodeConflict() from exc


@transaction.atomic
def update_channel_metadata(*, channel, data):
    channel = Channel.objects.select_for_update().get(id=channel.id)
    assert_expected_channel_revision(channel=channel, expected_revision=data.pop("expected_revision"))
    if "code" in data:
        data["code"] = normalize_channel_code(data["code"] or channel.name)
        if Channel.objects.filter(owner_company=channel.owner_company, code=data["code"]).exclude(id=channel.id).exists():
            raise ChannelCodeConflict()
    for field, value in data.items():
        setattr(channel, field, value)
    return bump_channel_revision(channel=channel, update_fields=data.keys())


@transaction.atomic
def update_channel_policy(*, channel, data):
    channel = Channel.objects.select_for_update().get(id=channel.id)
    assert_expected_channel_revision(channel=channel, expected_revision=data.pop("expected_revision"))
    policy, _ = ChannelPolicy.objects.select_for_update().get_or_create(channel=channel)
    for field, value in data.items():
        setattr(policy, field, value)
    policy.full_clean()
    policy.save()
    return bump_channel_revision(channel=channel, update_fields=[])


@transaction.atomic
def replace_channel_playlists(*, company, channel, playlists, expected_revision):
    channel = Channel.objects.select_for_update().get(id=channel.id)
    assert_expected_channel_revision(channel=channel, expected_revision=expected_revision)
    playlist_ids = [item["playlist_id"] for item in playlists]
    if len(playlist_ids) != len(set(playlist_ids)):
        raise ChannelPlaylistInvalid(fields={"playlists": ["No puede haber playlists duplicadas en el canal."]})
    resolved = []
    for item in playlists:
        resolved.append(
            {
                "playlist": assert_playlist_channel_available(company=company, playlist_id=item["playlist_id"]),
                "weight": item.get("weight", 1),
                "priority": item.get("priority", 0),
                "active_from": item.get("active_from"),
                "active_until": item.get("active_until"),
            }
        )
    channel.channel_playlists.all().delete()
    for item in resolved:
        ChannelPlaylist.objects.create(channel=channel, **item)
    return bump_channel_revision(channel=channel, update_fields=[])


@transaction.atomic
def duplicate_channel(*, company, channel, actor, name="", code=""):
    Company.objects.select_for_update().get(id=company.id)
    source = Channel.objects.select_for_update().get(id=channel.id)
    assert_channel_limit(company=company)
    duplicate_name = name or f"{source.name} copia"
    duplicate_code = next_available_channel_code(company=company, base_code=code or f"{source.code}-COPIA")
    copy = Channel.objects.create(
        owner_company=company,
        name=duplicate_name,
        code=duplicate_code,
        description=source.description,
        visibility=Channel.Visibility.PRIVATE,
        status=Channel.Status.DRAFT,
        created_by=actor,
    )
    source_policy, _ = ChannelPolicy.objects.get_or_create(channel=source)
    ChannelPolicy.objects.create(
        channel=copy,
        order_mode=source_policy.order_mode,
        repeat_song_gap_count=source_policy.repeat_song_gap_count,
        max_same_genre_in_row=source_policy.max_same_genre_in_row,
        avoid_same_tag_in_row=source_policy.avoid_same_tag_in_row,
        crossfade_ms=source_policy.crossfade_ms,
        fade_in_ms=source_policy.fade_in_ms,
        fade_out_ms=source_policy.fade_out_ms,
        normalize_loudness=source_policy.normalize_loudness,
        target_lufs=source_policy.target_lufs,
        settings=source_policy.settings,
    )
    for relation in source.channel_playlists.select_related("playlist").order_by("created_at", "id"):
        assert_playlist_channel_available(company=company, playlist_id=relation.playlist_id)
        ChannelPlaylist.objects.create(
            channel=copy,
            playlist=relation.playlist,
            weight=relation.weight,
            priority=relation.priority,
            active_from=relation.active_from,
            active_until=relation.active_until,
        )
    return copy


@transaction.atomic
def publish_channel(*, channel, company, published_by=None, expected_revision=None):
    channel = Channel.objects.select_for_update().get(id=channel.id)
    if channel.status == Channel.Status.ARCHIVED:
        raise ChannelNotPublishable(fields={"status": ["No se puede publicar un canal archivado."]})
    assert_channel_publishable(company=company, channel=channel)
    checksum = channel_checksum(channel=channel)
    latest = get_latest_published_channel_snapshot(channel=channel)

    if expected_revision is not None and channel.revision != expected_revision:
        if latest and latest.checksum == checksum:
            return latest
        raise ChannelRevisionConflict()

    if latest and latest.checksum == checksum:
        if channel.status != Channel.Status.PUBLISHED:
            channel.status = Channel.Status.PUBLISHED
            channel.published_at = latest.published_at
            bump_channel_revision(channel=channel, update_fields=["status", "published_at"])
        return latest

    version = channel.current_version + 1
    snapshot = ChannelSnapshot.objects.create(
        channel=channel,
        version=version,
        checksum=checksum,
        status=ChannelSnapshot.Status.PUBLISHED,
        policy_snapshot=channel_policy_snapshot(channel=channel),
        published_by=published_by,
        published_at=timezone.now(),
    )
    for relation in channel.channel_playlists.select_related("playlist").order_by("-priority", "playlist__name", "id"):
        playlist_snapshot = get_latest_published_snapshot(playlist=relation.playlist)
        ChannelSnapshotPlaylist.objects.create(
            snapshot=snapshot,
            playlist=relation.playlist,
            playlist_snapshot=playlist_snapshot,
            weight=relation.weight,
            priority=relation.priority,
            active_from=relation.active_from,
            active_until=relation.active_until,
        )
    channel.current_version = version
    channel.status = Channel.Status.PUBLISHED
    channel.published_at = snapshot.published_at
    bump_channel_revision(channel=channel, update_fields=["current_version", "status", "published_at"])
    for assignment in ZoneChannelAssignment.objects.filter(channel=channel, unassigned_at__isnull=True).select_related("zone"):
        from apps.playback.services import create_zone_operational_snapshot

        create_zone_operational_snapshot(zone=assignment.zone, reason="CHANNEL_PUBLISHED")
    return snapshot


@transaction.atomic
def archive_channel(*, channel, expected_revision):
    channel = Channel.objects.select_for_update().get(id=channel.id)
    assert_expected_channel_revision(channel=channel, expected_revision=expected_revision)
    if ZoneChannelAssignment.objects.filter(channel=channel, unassigned_at__isnull=True).exists():
        raise ChannelInUse()
    channel.status = Channel.Status.ARCHIVED
    channel.archived_at = timezone.now()
    return bump_channel_revision(channel=channel, update_fields=["status", "archived_at"])


@transaction.atomic
def reactivate_channel(*, company, channel, expected_revision):
    Company.objects.select_for_update().get(id=company.id)
    channel = Channel.objects.select_for_update().get(id=channel.id)
    assert_expected_channel_revision(channel=channel, expected_revision=expected_revision)
    assert_channel_limit(company=company)
    channel.status = Channel.Status.DRAFT
    channel.archived_at = None
    return bump_channel_revision(channel=channel, update_fields=["status", "archived_at"])


@transaction.atomic
def assign_channel_to_zone(*, company, zone, channel, actor, reason=""):
    zone = Zone.objects.select_for_update().select_related("site").get(id=zone.id, company=company)
    channel = Channel.objects.select_for_update().get(id=channel.id)
    if zone.status == Zone.Status.ARCHIVED or zone.site.status == Site.Status.ARCHIVED:
        raise ZoneChannelAssignmentInvalid(fields={"zone_id": ["La zona o su sede esta archivada."]})
    if channel.owner_company_id not in (None, company.id) or channel.status != Channel.Status.PUBLISHED:
        raise ZoneChannelAssignmentInvalid(fields={"channel_id": ["El canal debe estar publicado y pertenecer a tu empresa."]})
    if not get_latest_published_channel_snapshot(channel=channel):
        raise ZoneChannelAssignmentInvalid(fields={"channel_id": ["El canal necesita una version publicada."]})
    now = timezone.now()
    current = ZoneChannelAssignment.objects.select_for_update().filter(zone=zone, unassigned_at__isnull=True).first()
    if current and current.channel_id == channel.id:
        return current
    if current:
        current.unassigned_at = now
        current.unassigned_by = actor
        current.reason = reason or "Cambio de canal"
        current.save(update_fields=["unassigned_at", "unassigned_by", "reason"])
    assignment = ZoneChannelAssignment.objects.create(
        company=company,
        zone=zone,
        channel=channel,
        assigned_by=actor,
        assigned_at=now,
        reason=reason,
    )
    from apps.playback.services import create_zone_operational_snapshot

    create_zone_operational_snapshot(zone=zone, reason="CHANNEL_ASSIGNED")
    return assignment


@transaction.atomic
def unassign_channel_from_zone(*, company, zone, actor, reason=""):
    zone = Zone.objects.select_for_update().get(id=zone.id, company=company)
    current = ZoneChannelAssignment.objects.select_for_update().filter(zone=zone, unassigned_at__isnull=True).first()
    if not current:
        return None
    current.unassigned_at = timezone.now()
    current.unassigned_by = actor
    current.reason = reason or "Canal retirado"
    current.save(update_fields=["unassigned_at", "unassigned_by", "reason"])
    from apps.playback.services import create_zone_operational_snapshot

    create_zone_operational_snapshot(zone=zone, reason="CHANNEL_UNASSIGNED")
    return current


@transaction.atomic
def update_playlist_metadata(*, playlist, data):
    playlist = Playlist.objects.select_for_update().get(id=playlist.id)
    assert_expected_revision(playlist=playlist, expected_revision=data.pop("expected_revision"))
    if "code" in data:
        data["code"] = normalize_playlist_code(data["code"] or playlist.name)
        if Playlist.objects.filter(owner_company=playlist.owner_company, code=data["code"]).exclude(id=playlist.id).exists():
            raise PlaylistCodeConflict()
    for field, value in data.items():
        setattr(playlist, field, value)
    return bump_revision(playlist=playlist, update_fields=data.keys())


@transaction.atomic
def add_playlist_item(*, company, playlist, song_id, weight, expected_revision, actor):
    playlist = Playlist.objects.select_for_update().get(id=playlist.id)
    assert_expected_revision(playlist=playlist, expected_revision=expected_revision)
    song = assert_song_available(company=company, song_id=song_id)
    max_position = playlist.items.order_by("-position").values_list("position", flat=True).first() or 0
    PlaylistItem.objects.create(
        playlist=playlist,
        song=song,
        position=max_position + 1,
        weight=weight,
        added_by=actor,
    )
    return bump_revision(playlist=playlist, update_fields=[])


@transaction.atomic
def replace_playlist_items(*, company, playlist, items, expected_revision, actor):
    playlist = Playlist.objects.select_for_update().get(id=playlist.id)
    assert_expected_revision(playlist=playlist, expected_revision=expected_revision)
    resolved = [
        {
            "song": assert_song_available(company=company, song_id=item["song_id"]),
            "position": item["position"],
            "weight": item.get("weight", 1),
        }
        for item in sorted(items, key=lambda value: value["position"])
    ]
    playlist.items.all().delete()
    for item in resolved:
        PlaylistItem.objects.create(
            playlist=playlist,
            song=item["song"],
            position=item["position"],
            weight=item["weight"],
            added_by=actor,
        )
    return bump_revision(playlist=playlist, update_fields=[])


@transaction.atomic
def remove_playlist_item(*, playlist, item, expected_revision):
    playlist = Playlist.objects.select_for_update().get(id=playlist.id)
    assert_expected_revision(playlist=playlist, expected_revision=expected_revision)
    item.delete()
    for position, current in enumerate(playlist.items.order_by("position", "id"), start=1):
        if current.position != position:
            current.position = position
            current.save(update_fields=["position", "updated_at"])
    return bump_revision(playlist=playlist, update_fields=[])


@transaction.atomic
def reorder_playlist_items(*, playlist, item_ids, expected_revision):
    playlist = Playlist.objects.select_for_update().get(id=playlist.id)
    assert_expected_revision(playlist=playlist, expected_revision=expected_revision)
    current_items = list(playlist.items.order_by("position", "id"))
    current_ids = [item.id for item in current_items]
    if set(current_ids) != set(item_ids) or len(current_ids) != len(item_ids):
        raise PlaylistOrderConflict()
    item_by_id = {item.id: item for item in current_items}
    for position, item_id in enumerate(item_ids, start=1):
        item = item_by_id[item_id]
        item.position = 100000 + position
        item.save(update_fields=["position", "updated_at"])
    for position, item_id in enumerate(item_ids, start=1):
        item = item_by_id[item_id]
        item.position = position
        item.save(update_fields=["position", "updated_at"])
    return bump_revision(playlist=playlist, update_fields=[])


@transaction.atomic
def duplicate_playlist(*, company, playlist, actor, name="", code=""):
    Company.objects.select_for_update().get(id=company.id)
    source = Playlist.objects.select_for_update().get(id=playlist.id)
    assert_playlist_limit(company=company)
    for item in source.items.order_by("position"):
        assert_song_available(company=company, song_id=item.song_id)
    duplicate_name = name or f"{source.name} copia"
    duplicate_code = next_available_code(company=company, base_code=code or f"{source.code}-COPIA")
    copy = Playlist.objects.create(
        owner_company=company,
        name=duplicate_name,
        code=duplicate_code,
        description=source.description,
        playlist_type=Playlist.PlaylistType.MANUAL,
        visibility=Playlist.Visibility.PRIVATE,
        status=Playlist.Status.DRAFT,
        created_by=actor,
    )
    for item in source.items.order_by("position", "id"):
        PlaylistItem.objects.create(
            playlist=copy,
            song=item.song,
            position=item.position,
            weight=item.weight,
            active_from=item.active_from,
            active_until=item.active_until,
            added_by=actor,
        )
    return copy


@transaction.atomic
def publish_playlist(*, playlist, company=None, published_by=None, expected_revision=None):
    playlist = Playlist.objects.select_for_update().get(id=playlist.id)
    if not playlist.items.exists():
        raise PlaylistNotPublishable(fields={"items": ["La playlist debe tener al menos una cancion."]})
    if company is not None:
        assert_all_playlist_songs_available(company=company, playlist=playlist)
    checksum = playlist_checksum(playlist=playlist)
    latest = get_latest_published_snapshot(playlist=playlist)

    if expected_revision is not None and playlist.revision != expected_revision:
        if latest and latest.checksum == checksum:
            return latest
        raise PlaylistRevisionConflict()

    if latest and latest.checksum == checksum:
        if playlist.status != Playlist.Status.PUBLISHED:
            playlist.status = Playlist.Status.PUBLISHED
            playlist.published_at = latest.published_at
            bump_revision(playlist=playlist, update_fields=["status", "published_at"])
        return latest

    version = playlist.current_version + 1
    snapshot = PlaylistSnapshot.objects.create(
        playlist=playlist,
        version=version,
        checksum=checksum,
        status=PlaylistSnapshot.Status.PUBLISHED,
        published_by=published_by,
        published_at=timezone.now(),
    )
    for item in playlist.items.order_by("position", "id"):
        PlaylistSnapshotItem.objects.create(
            snapshot=snapshot,
            song=item.song,
            position=item.position,
            weight=item.weight,
        )
    playlist.current_version = version
    playlist.status = Playlist.Status.PUBLISHED
    playlist.published_at = snapshot.published_at
    bump_revision(playlist=playlist, update_fields=["current_version", "status", "published_at"])
    return snapshot


@transaction.atomic
def archive_playlist(*, playlist, expected_revision):
    playlist = Playlist.objects.select_for_update().get(id=playlist.id)
    assert_expected_revision(playlist=playlist, expected_revision=expected_revision)
    if playlist_has_schedule_usage(playlist=playlist):
        raise PlaylistInUse()
    playlist.status = Playlist.Status.ARCHIVED
    playlist.archived_at = timezone.now()
    return bump_revision(playlist=playlist, update_fields=["status", "archived_at"])


@transaction.atomic
def reactivate_playlist(*, company, playlist, expected_revision):
    Company.objects.select_for_update().get(id=company.id)
    playlist = Playlist.objects.select_for_update().get(id=playlist.id)
    assert_expected_revision(playlist=playlist, expected_revision=expected_revision)
    assert_playlist_limit(company=company)
    playlist.status = Playlist.Status.DRAFT
    playlist.archived_at = None
    return bump_revision(playlist=playlist, update_fields=["status", "archived_at"])
