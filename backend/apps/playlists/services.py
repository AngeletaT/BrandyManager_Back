import hashlib

from django.db import transaction
from django.utils import timezone

from apps.playlists.models import PlaylistSnapshot, PlaylistSnapshotItem


@transaction.atomic
def publish_playlist(*, playlist, published_by=None):
    playlist = playlist.__class__.objects.select_for_update().get(id=playlist.id)
    version = playlist.current_version + 1
    source = "|".join(f"{item.song_id}:{item.position}:{item.weight}" for item in playlist.items.order_by("position"))
    checksum = hashlib.sha256(source.encode("utf-8")).hexdigest()

    snapshot = PlaylistSnapshot.objects.create(
        playlist=playlist,
        version=version,
        checksum=checksum,
        status=PlaylistSnapshot.Status.PUBLISHED,
        published_by=published_by,
        published_at=timezone.now(),
    )
    for item in playlist.items.order_by("position"):
        PlaylistSnapshotItem.objects.create(
            snapshot=snapshot,
            song=item.song,
            position=item.position,
            weight=item.weight,
        )
    playlist.current_version = version
    playlist.status = playlist.Status.PUBLISHED
    playlist.published_at = snapshot.published_at
    playlist.save(update_fields=["current_version", "status", "published_at", "updated_at"])
    return snapshot
