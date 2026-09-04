import hashlib

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.billing.selectors import get_current_subscription_for_company
from apps.catalog.selectors import get_accessible_song_by_id
from apps.organizations.models import Company
from apps.playlists.exceptions import (
    PlaylistCodeConflict,
    PlaylistContentUnavailable,
    PlaylistInUse,
    PlaylistLimitReached,
    PlaylistNotPublishable,
    PlaylistOrderConflict,
    PlaylistRevisionConflict,
)
from apps.playlists.models import Playlist, PlaylistItem, PlaylistSnapshot, PlaylistSnapshotItem
from apps.playlists.selectors import count_billable_playlists, get_latest_published_snapshot, playlist_has_schedule_usage


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


def playlist_checksum(*, playlist):
    source = "|".join(
        f"{item.song_id}:{item.position}:{item.weight}"
        for item in playlist.items.select_related("song").order_by("position", "id")
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def assert_expected_revision(*, playlist, expected_revision):
    if playlist.revision != expected_revision:
        raise PlaylistRevisionConflict()


def assert_playlist_limit(*, company):
    subscription = get_current_subscription_for_company(company=company)
    limits = subscription.effective_limits() if subscription else {}
    limit = limits.get("playlists")
    if limit is not None and count_billable_playlists(company=company) >= limit:
        raise PlaylistLimitReached()


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
