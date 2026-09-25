import hashlib
import json

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone


def resolve_effective_policy(*, zone, at=None):
    assignments = (
        zone.company.playback_policy_assignments.filter(is_active=True)
        .select_related("policy", "scope")
        .order_by("-is_locked", "-priority", "-created_at")
    )
    return assignments.first()


def can_execute_playback_action(*, user_has_permission, policy, action):
    if not user_has_permission:
        return False
    mapping = {
        "pause": policy.allow_pause,
        "skip": policy.allow_skip,
        "change_channel": policy.allow_channel_change,
        "volume": policy.allow_local_volume_change,
        "manual_message": policy.allow_manual_message,
    }
    return bool(mapping.get(action, False))


@transaction.atomic
def create_manifest(*, zone, operational_snapshot, expires_at=None):
    from apps.catalog.models import AudioAsset, AudioContent
    from apps.organizations.models import Zone
    from apps.playback.models import ContentManifest, ContentManifestItem
    from apps.playlists.models import ContentAccessGrant

    zone = Zone.objects.select_for_update().get(id=zone.id)
    if operational_snapshot.zone_id != zone.id or operational_snapshot.company_id != zone.company_id:
        raise ValidationError({"operational_snapshot": "El snapshot no corresponde a la zona indicada."})
    if operational_snapshot.status != operational_snapshot.Status.READY:
        raise ValidationError({"operational_snapshot": "El snapshot operativo no esta disponible."})

    generated_at = timezone.now()
    expires_at = expires_at or generated_at + settings.BM_CONTENT_MANIFEST_TTL
    if expires_at <= generated_at:
        raise ValidationError({"expires_at": "La caducidad debe ser posterior a la generacion."})

    snapshot_assets = operational_snapshot.snapshot_data.get("assets", [])
    asset_ids = {
        item.get("audio_asset_id")
        for item in snapshot_assets
        if item.get("asset_available") and item.get("audio_asset_id")
    }
    shared_content_ids = ContentAccessGrant.objects.filter(
        company=zone.company,
        audio_content__isnull=False,
        revoked_at__isnull=True,
    ).values("audio_content_id")
    assets = list(
        AudioAsset.objects.select_related("audio_content")
        .filter(
            id__in=asset_ids,
            processing_status=AudioAsset.ProcessingStatus.READY,
            audio_content__status=AudioContent.Status.READY,
            audio_content__is_active=True,
            audio_content__rights_verified_at__isnull=False,
        )
        .exclude(audio_content__rights_holder="")
        .exclude(audio_content__rights_reference="")
        .filter(
            Q(
                audio_content__visibility=AudioContent.Visibility.GLOBAL,
                audio_content__owner_company__isnull=True,
            )
            | Q(audio_content__owner_company=zone.company)
            | Q(
                audio_content__visibility=AudioContent.Visibility.SHARED,
                audio_content_id__in=shared_content_ids,
            )
        )
        .order_by("id")
    )
    checksum_payload = {
        "operational_snapshot_id": str(operational_snapshot.id),
        "assets": [
            {"id": str(asset.id), "checksum": asset.checksum_sha256, "size": asset.size_bytes}
            for asset in assets
        ],
    }
    version = zone.content_manifests.order_by("-version").values_list("version", flat=True).first() or 0
    ContentManifest.objects.filter(zone=zone, status=ContentManifest.Status.READY).update(
        status=ContentManifest.Status.SUPERSEDED
    )
    manifest = ContentManifest.objects.create(
        company=zone.company,
        zone=zone,
        operational_snapshot=operational_snapshot,
        version=version + 1,
        status=ContentManifest.Status.READY if assets else ContentManifest.Status.ERROR,
        generated_at=generated_at,
        valid_from=generated_at,
        expires_at=expires_at,
        checksum=_snapshot_checksum(payload=checksum_payload),
        schedule_version=(operational_snapshot.schedule_snapshot.version if operational_snapshot.schedule_snapshot_id else None),
        policy_version=(operational_snapshot.channel_snapshot.version if operational_snapshot.channel_snapshot_id else None),
        total_size_bytes=sum(asset.size_bytes for asset in assets),
        metadata={"asset_count": len(assets), "execution_observed": False},
    )
    ContentManifestItem.objects.bulk_create(
        [
            ContentManifestItem(
                manifest=manifest,
                audio_asset=asset,
                priority=index,
                is_required=True,
                reason=ContentManifestItem.Reason.PLAYLIST,
                checksum_sha256=asset.checksum_sha256,
                size_bytes=asset.size_bytes,
            )
            for index, asset in enumerate(assets, start=1)
        ]
    )
    return manifest


def _zone_operational_snapshot_payload(*, zone, active_assignment, channel_snapshot, schedule_snapshot, generated_at):
    playlist_snapshots = []
    assets = []
    included_snapshot_ids = set()

    def include_playlist_snapshot(snapshot, *, weight=1, priority=0, active_from=None, active_until=None):
        if not snapshot or str(snapshot.id) in included_snapshot_ids:
            return
        included_snapshot_ids.add(str(snapshot.id))
        playlist_snapshots.append(
            {
                "playlist_id": str(snapshot.playlist_id),
                "playlist_snapshot_id": str(snapshot.id),
                "playlist_snapshot_version": snapshot.version,
                "weight": weight,
                "priority": priority,
                "active_from": active_from.isoformat() if active_from else None,
                "active_until": active_until.isoformat() if active_until else None,
            }
        )
        for item in snapshot.items.select_related("song__audio_content").prefetch_related("song__audio_content__assets"):
            ready_asset = item.song.audio_content.assets.filter(
                processing_status="READY", is_primary=True
            ).order_by("-version", "id").first()
            assets.append(
                {
                    "playlist_snapshot_id": str(snapshot.id),
                    "playlist_snapshot_item_id": str(item.id),
                    "song_id": str(item.song_id),
                    "audio_content_id": str(item.song.audio_content_id),
                    "audio_asset_id": str(ready_asset.id) if ready_asset else None,
                    "asset_available": bool(ready_asset),
                    "position": item.position,
                    "weight": item.weight,
                }
            )

    if channel_snapshot:
        for relation in channel_snapshot.playlists.select_related("playlist", "playlist_snapshot").prefetch_related(
            "playlist_snapshot__items__song__audio_content__assets",
            "playlist_snapshot__items__song__genre",
        ):
            include_playlist_snapshot(
                relation.playlist_snapshot,
                weight=relation.weight,
                priority=relation.priority,
                active_from=relation.active_from,
                active_until=relation.active_until,
            )

    schedule_data = schedule_snapshot.snapshot_data if schedule_snapshot else None
    if schedule_data:
        from apps.playlists.models import PlaylistSnapshot

        referenced_ids = {
            entry.get("playlist_snapshot_id")
            for collection in ("blocks", "exceptions")
            for entry in schedule_data.get(collection, [])
            if entry.get("playlist_snapshot_id")
        }
        for snapshot in PlaylistSnapshot.objects.filter(id__in=referenced_ids).prefetch_related(
            "items__song__audio_content__assets"
        ):
            include_playlist_snapshot(snapshot)

    return {
        "schema_version": 1,
        "generated_at": generated_at.isoformat(),
        "zone": {
            "id": str(zone.id),
            "site_id": str(zone.site_id),
            "company_id": str(zone.company_id),
            "timezone": zone.effective_timezone,
        },
        "channel_assignment": {
            "id": str(active_assignment.id) if active_assignment else None,
            "assigned_at": active_assignment.assigned_at.isoformat() if active_assignment else None,
        },
        "channel": {
            "id": str(active_assignment.channel_id) if active_assignment else None,
            "snapshot_id": str(channel_snapshot.id) if channel_snapshot else None,
            "snapshot_version": channel_snapshot.version if channel_snapshot else None,
        },
        "schedule": {
            "snapshot_id": str(schedule_snapshot.id) if schedule_snapshot else None,
            "snapshot_version": schedule_snapshot.version if schedule_snapshot else None,
            "snapshot_data": schedule_data,
        },
        "playlist_snapshots": playlist_snapshots,
        "assets": assets,
        "execution_observed": False,
    }


def _snapshot_checksum(*, payload):
    source = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


@transaction.atomic
def create_zone_operational_snapshot(*, zone, reason):
    from apps.organizations.models import Zone, ZoneChannelAssignment
    from apps.playback.models import ZoneOperationalSnapshot
    from apps.playlists.selectors import get_latest_published_channel_snapshot
    from apps.scheduling.selectors import get_latest_published_schedule_snapshot, resolve_effective_schedule_for_zone

    zone = Zone.objects.select_for_update().select_related("company", "site").get(id=zone.id)
    active_assignment = (
        ZoneChannelAssignment.objects.select_for_update()
        .filter(zone=zone, unassigned_at__isnull=True)
        .select_related("channel")
        .first()
    )
    channel_snapshot = get_latest_published_channel_snapshot(channel=active_assignment.channel) if active_assignment else None
    effective_schedule = resolve_effective_schedule_for_zone(zone=zone, at=timezone.now())
    schedule = effective_schedule.get("schedule")
    schedule_snapshot = get_latest_published_schedule_snapshot(schedule=schedule) if schedule else None
    generated_at = timezone.now()
    payload = _zone_operational_snapshot_payload(
        zone=zone,
        active_assignment=active_assignment,
        channel_snapshot=channel_snapshot,
        schedule_snapshot=schedule_snapshot,
        generated_at=generated_at,
    )
    latest_version = zone.operational_snapshots.order_by("-version").values_list("version", flat=True).first() or 0
    ZoneOperationalSnapshot.objects.filter(zone=zone, status=ZoneOperationalSnapshot.Status.READY).update(
        status=ZoneOperationalSnapshot.Status.SUPERSEDED
    )
    snapshot = ZoneOperationalSnapshot.objects.create(
        company=zone.company,
        zone=zone,
        version=latest_version + 1,
        status=ZoneOperationalSnapshot.Status.READY,
        channel=active_assignment.channel if active_assignment else None,
        channel_snapshot=channel_snapshot,
        schedule_snapshot=schedule_snapshot,
        checksum=_snapshot_checksum(payload=payload),
        generated_at=generated_at,
        reason=reason,
        snapshot_data=payload,
    )
    return snapshot


@transaction.atomic
def get_or_create_player_runtime(*, device, force_refresh=False):
    """Return the durable, published runtime contract consumed by Go."""
    from apps.devices.models import Device
    from apps.playback.models import ContentManifest, ZoneOperationalSnapshot

    device = Device.objects.select_for_update(of=("self",)).select_related("company", "zone", "zone__site").get(id=device.id)
    if not device.zone_id:
        raise ValidationError({"device": "El dispositivo no tiene zona asignada."})
    snapshot = (
        ZoneOperationalSnapshot.objects.filter(
            company=device.company,
            zone=device.zone,
            status=ZoneOperationalSnapshot.Status.READY,
        )
        .select_related("channel", "channel_snapshot", "schedule_snapshot")
        .order_by("-version")
        .first()
    )
    from apps.scheduling.selectors import get_latest_published_schedule_snapshot, resolve_effective_schedule_for_zone

    effective = resolve_effective_schedule_for_zone(zone=device.zone, at=timezone.now())
    effective_schedule = effective.get("schedule")
    expected_schedule_snapshot = (
        get_latest_published_schedule_snapshot(schedule=effective_schedule) if effective_schedule else None
    )
    if (snapshot and snapshot.schedule_snapshot_id != getattr(expected_schedule_snapshot, "id", None)) or (
        not snapshot and expected_schedule_snapshot
    ):
        snapshot = create_zone_operational_snapshot(
            zone=device.zone,
            reason="RUNTIME_CONFIGURATION_ROLLOVER",
        )
        snapshot = ZoneOperationalSnapshot.objects.select_related(
            "channel", "channel_snapshot", "schedule_snapshot"
        ).get(id=snapshot.id)
    if not snapshot:
        return {
            "device": _runtime_device(device),
            "reason": "NO_PUBLISHED_CONFIGURATION",
            "operational_snapshot": None,
            "manifest": None,
        }

    now = timezone.now()
    manifest = (
        ContentManifest.objects.filter(
            zone=device.zone,
            operational_snapshot=snapshot,
            status__in=[ContentManifest.Status.READY, ContentManifest.Status.ERROR],
            expires_at__gt=now,
        )
        .prefetch_related("items__audio_asset__audio_content")
        .order_by("-version")
        .first()
    )
    if force_refresh or not manifest:
        manifest = create_manifest(zone=device.zone, operational_snapshot=snapshot)
        manifest = ContentManifest.objects.prefetch_related("items__audio_asset__audio_content").get(id=manifest.id)

    reason = None
    if not snapshot.channel_id:
        reason = "NO_CHANNEL_ASSIGNED"
    elif not snapshot.schedule_snapshot_id:
        reason = "NO_SCHEDULE_CONTENT"
    elif manifest.status != ContentManifest.Status.READY:
        reason = "NO_AVAILABLE_ASSETS"

    policy = snapshot.channel_snapshot.policy_snapshot if snapshot.channel_snapshot_id else {}
    return {
        "device": _runtime_device(device),
        "reason": reason,
        "operational_snapshot": {
            "id": str(snapshot.id),
            "version": snapshot.version,
            "checksum": snapshot.checksum,
            "generated_at": snapshot.generated_at,
            "channel_id": str(snapshot.channel_id) if snapshot.channel_id else None,
            "channel_snapshot_id": str(snapshot.channel_snapshot_id) if snapshot.channel_snapshot_id else None,
            "schedule_snapshot_id": str(snapshot.schedule_snapshot_id) if snapshot.schedule_snapshot_id else None,
            "data": snapshot.snapshot_data,
            "playback_policy": policy,
        },
        "manifest": _runtime_manifest(manifest),
    }


def _runtime_device(device):
    from apps.organizations.models import ZoneChannelAssignment

    channel_id = (
        ZoneChannelAssignment.objects.filter(zone_id=device.zone_id, unassigned_at__isnull=True)
        .values_list("channel_id", flat=True)
        .first()
        if device.zone_id
        else None
    )
    return {
        "id": str(device.id),
        "company_id": str(device.company_id),
        "zone_id": str(device.zone_id) if device.zone_id else None,
        "channel_id": str(channel_id) if channel_id else None,
        "configuration_version": device.configuration_version,
        "zone_timezone": device.zone.effective_timezone if device.zone_id else None,
    }


def _runtime_manifest(manifest):
    if not manifest:
        return None
    return {
        "id": str(manifest.id),
        "version": manifest.version,
        "status": manifest.status,
        "checksum": manifest.checksum,
        "generated_at": manifest.generated_at,
        "valid_from": manifest.valid_from,
        "valid_until": manifest.expires_at,
        "total_size_bytes": manifest.total_size_bytes,
        "items": [
            {
                "asset_id": str(item.audio_asset_id),
                "audio_content_id": str(item.audio_asset.audio_content_id),
                "title": item.audio_asset.audio_content.title,
                "duration_ms": item.audio_asset.duration_ms or item.audio_asset.audio_content.duration_ms,
                "mime_type": item.audio_asset.mime_type,
                "checksum_sha256": item.checksum_sha256,
                "size_bytes": item.size_bytes,
                "stream_path": f"/api/player/audio/assets/{item.audio_asset_id}/stream/",
                "offline_cacheable": True,
            }
            for item in manifest.items.all()
        ],
    }
