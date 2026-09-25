import hashlib
import json
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.authorization.services import get_company_scope, get_or_create_site_scope, get_or_create_zone_scope
from apps.organizations.models import ResourceScope, Site, Zone
from apps.playlists.models import Channel, Playlist
from apps.playlists.selectors import get_accessible_playlist_by_id, get_latest_published_channel_snapshot, get_latest_published_snapshot
from apps.scheduling.exceptions import (
    ScheduleAssignmentInvalid,
    ScheduleConflict,
    ScheduleContentUnavailable,
    ScheduleNotPublishable,
    ScheduleRevisionConflict,
)
from apps.scheduling.models import Schedule, ScheduleAssignment, ScheduleBlock, ScheduleException, ScheduleSnapshot
from apps.scheduling.selectors import (
    list_assignment_conflicts,
    list_block_conflicts,
    list_exception_conflicts,
    resolve_effective_schedule_for_zone,
)


def validate_timezone_name(value):
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValidationError({"timezone": ["Zona horaria no valida."]}) from exc
    return value


def assert_expected_revision(*, schedule, expected_revision):
    if schedule.revision != expected_revision:
        raise ScheduleRevisionConflict()


def bump_revision(*, schedule, update_fields):
    schedule.revision += 1
    fields = list(update_fields)
    if "revision" not in fields:
        fields.append("revision")
    if "updated_at" not in fields:
        fields.append("updated_at")
    schedule.save(update_fields=fields)
    return schedule


def assert_playlist_schedulable(*, company, playlist_id):
    playlist = get_accessible_playlist_by_id(company=company, playlist_id=playlist_id)
    if not playlist:
        raise ScheduleContentUnavailable(fields={"playlist_id": ["La playlist no esta disponible para esta empresa."]})
    if playlist.status != Playlist.Status.PUBLISHED or not get_latest_published_snapshot(playlist=playlist):
        raise ScheduleContentUnavailable(fields={"playlist_id": ["La playlist debe estar publicada para programarse."]})
    return playlist


def _iso_or_none(value):
    return value.isoformat() if value else None


def schedule_snapshot_payload(*, schedule, version):
    blocks = []
    for block in schedule.blocks.select_related("playlist", "channel").order_by("day_of_week", "start_time", "-priority", "id"):
        playlist_snapshot = get_latest_published_snapshot(playlist=block.playlist) if block.playlist_id else None
        channel_snapshot = get_latest_published_channel_snapshot(channel=block.channel) if block.channel_id else None
        blocks.append(
            {
                "id": str(block.id),
                "day_of_week": block.day_of_week,
                "start_time": block.start_time.isoformat(),
                "end_time": block.end_time.isoformat(),
                "content_type": block.content_type,
                "playlist_id": str(block.playlist_id) if block.playlist_id else None,
                "playlist_snapshot_id": str(playlist_snapshot.id) if playlist_snapshot else None,
                "playlist_snapshot_version": playlist_snapshot.version if playlist_snapshot else None,
                "channel_id": str(block.channel_id) if block.channel_id else None,
                "channel_snapshot_id": str(channel_snapshot.id) if channel_snapshot else None,
                "channel_snapshot_version": channel_snapshot.version if channel_snapshot else None,
                "priority": block.priority,
                "volume_override": block.volume_override,
            }
        )
    exceptions = []
    for exception in schedule.exceptions.select_related("playlist", "channel").order_by("date", "start_time", "-priority", "id"):
        playlist_snapshot = get_latest_published_snapshot(playlist=exception.playlist) if exception.playlist_id else None
        channel_snapshot = get_latest_published_channel_snapshot(channel=exception.channel) if exception.channel_id else None
        exceptions.append(
            {
                "id": str(exception.id),
                "date": exception.date.isoformat(),
                "start_time": exception.start_time.isoformat(),
                "end_time": exception.end_time.isoformat(),
                "action": exception.action,
                "playlist_id": str(exception.playlist_id) if exception.playlist_id else None,
                "playlist_snapshot_id": str(playlist_snapshot.id) if playlist_snapshot else None,
                "playlist_snapshot_version": playlist_snapshot.version if playlist_snapshot else None,
                "channel_id": str(exception.channel_id) if exception.channel_id else None,
                "channel_snapshot_id": str(channel_snapshot.id) if channel_snapshot else None,
                "channel_snapshot_version": channel_snapshot.version if channel_snapshot else None,
                "priority": exception.priority,
                "volume_override": exception.volume_override,
                "description": exception.description,
            }
        )
    assignments = []
    for assignment in schedule.assignments.select_related("scope", "scope__site", "scope__zone").order_by("-is_locked", "-priority", "created_at", "id"):
        assignments.append(
            {
                "id": str(assignment.id),
                "scope": {
                    "id": str(assignment.scope_id),
                    "type": assignment.scope.scope_type,
                    "site_id": str(assignment.scope.site_id) if assignment.scope.site_id else None,
                    "zone_id": str(assignment.scope.zone_id) if assignment.scope.zone_id else None,
                },
                "priority": assignment.priority,
                "is_locked": assignment.is_locked,
                "starts_at": _iso_or_none(assignment.starts_at),
                "ends_at": _iso_or_none(assignment.ends_at),
                "is_active": assignment.is_active,
            }
        )
    return {
        "schedule_id": str(schedule.id),
        "schedule_version": version,
        "timezone": schedule.timezone,
        "valid_from": _iso_or_none(schedule.valid_from),
        "valid_until": _iso_or_none(schedule.valid_until),
        "blocks": blocks,
        "exceptions": exceptions,
        "assignments": assignments,
    }


def schedule_snapshot_checksum(*, payload):
    source = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def resolve_scope_from_payload(*, company, scope_type, site_id=None, zone_id=None):
    if scope_type == ResourceScope.ScopeType.COMPANY:
        return get_company_scope(company=company)
    if scope_type == ResourceScope.ScopeType.SITE:
        if not site_id:
            raise ScheduleAssignmentInvalid(fields={"site_id": ["La sede es obligatoria para scope SITE."]})
        site = Site.objects.filter(company=company, id=site_id).first()
        if not site or site.status == Site.Status.ARCHIVED:
            raise ScheduleAssignmentInvalid(fields={"site_id": ["La sede no existe, no pertenece a tu empresa o esta archivada."]})
        return get_or_create_site_scope(site=site)
    if scope_type == ResourceScope.ScopeType.ZONE:
        if not zone_id:
            raise ScheduleAssignmentInvalid(fields={"zone_id": ["La zona es obligatoria para scope ZONE."]})
        zone = Zone.objects.select_related("site").filter(company=company, id=zone_id).first()
        if not zone or zone.status == Zone.Status.ARCHIVED or zone.site.status == Site.Status.ARCHIVED:
            raise ScheduleAssignmentInvalid(fields={"zone_id": ["La zona no existe, no pertenece a tu empresa o esta archivada."]})
        return get_or_create_zone_scope(zone=zone)
    raise ScheduleAssignmentInvalid(fields={"scope_type": ["Scope no admitido en Fase 3."]})


def validate_block_conflicts(*, block):
    conflicts = list_block_conflicts(block=block)
    if conflicts:
        raise ScheduleConflict(
            fields={"start_time": ["Existe otro bloque solapado con la misma prioridad."]},
            conflicts=[
                {
                    "id": str(conflict.id),
                    "day_of_week": conflict.day_of_week,
                    "start_time": conflict.start_time.isoformat(),
                    "end_time": conflict.end_time.isoformat(),
                    "priority": conflict.priority,
                }
                for conflict in conflicts
            ],
        )


def validate_exception_conflicts(*, exception):
    conflicts = list_exception_conflicts(exception=exception)
    if conflicts:
        raise ScheduleConflict(
            fields={"start_time": ["Existe otra excepcion solapada con la misma prioridad."]},
            conflicts=[
                {
                    "id": str(conflict.id),
                    "date": conflict.date.isoformat(),
                    "start_time": conflict.start_time.isoformat(),
                    "end_time": conflict.end_time.isoformat(),
                    "priority": conflict.priority,
                }
                for conflict in conflicts
            ],
        )


def validate_assignment_conflicts(*, assignment):
    conflicts = list_assignment_conflicts(assignment=assignment)
    if conflicts:
        raise ScheduleConflict(
            fields={"scope": ["Existe otra asignacion activa al mismo destino con la misma prioridad."]},
            conflicts=[
                {
                    "id": str(conflict.id),
                    "schedule": {"id": str(conflict.schedule_id), "name": conflict.schedule.name},
                    "scope_id": str(conflict.scope_id),
                    "priority": conflict.priority,
                }
                for conflict in conflicts
            ],
        )


@transaction.atomic
def create_schedule(*, company, data, actor):
    validate_timezone_name(data["timezone"])
    schedule = Schedule(
        company=company,
        name=data["name"],
        description=data.get("description", ""),
        timezone=data["timezone"],
        valid_from=data.get("valid_from"),
        valid_until=data.get("valid_until"),
        created_by=actor,
    )
    schedule.full_clean()
    schedule.save()
    return schedule


@transaction.atomic
def update_schedule_metadata(*, schedule, data):
    schedule = Schedule.objects.select_for_update().get(id=schedule.id)
    assert_expected_revision(schedule=schedule, expected_revision=data.pop("expected_revision"))
    if "timezone" in data:
        validate_timezone_name(data["timezone"])
    for field, value in data.items():
        setattr(schedule, field, value)
    schedule.full_clean()
    return bump_revision(schedule=schedule, update_fields=data.keys())


@transaction.atomic
def create_schedule_block(*, company, schedule, data):
    schedule = Schedule.objects.select_for_update().get(id=schedule.id)
    assert_expected_revision(schedule=schedule, expected_revision=data.pop("expected_revision"))
    playlist = None
    if data["content_type"] == ScheduleBlock.ContentType.PLAYLIST:
        playlist = assert_playlist_schedulable(company=company, playlist_id=data["playlist_id"])
    block = ScheduleBlock(
        schedule=schedule,
        day_of_week=data["day_of_week"],
        start_time=data["start_time"],
        end_time=data["end_time"],
        content_type=data["content_type"],
        playlist=playlist,
        priority=data.get("priority", 0),
        volume_override=data.get("volume_override"),
    )
    block.full_clean()
    block.save()
    validate_block_conflicts(block=block)
    return bump_revision(schedule=schedule, update_fields=[])


@transaction.atomic
def update_schedule_block(*, company, schedule, block, data):
    schedule = Schedule.objects.select_for_update().get(id=schedule.id)
    block = ScheduleBlock.objects.select_for_update().get(id=block.id, schedule=schedule)
    assert_expected_revision(schedule=schedule, expected_revision=data.pop("expected_revision"))
    if "content_type" in data:
        block.content_type = data["content_type"]
        block.playlist = None
        block.channel = None
    if "playlist_id" in data:
        block.playlist = assert_playlist_schedulable(company=company, playlist_id=data["playlist_id"]) if data["playlist_id"] else None
    for field in ["day_of_week", "start_time", "end_time", "priority", "volume_override"]:
        if field in data:
            setattr(block, field, data[field])
    if block.content_type == ScheduleBlock.ContentType.PLAYLIST and not block.playlist_id:
        raise ScheduleContentUnavailable(fields={"playlist_id": ["La playlist es obligatoria para bloques PLAYLIST."]})
    if block.content_type == ScheduleBlock.ContentType.SILENCE:
        block.playlist = None
        block.channel = None
    block.full_clean()
    block.save()
    validate_block_conflicts(block=block)
    return bump_revision(schedule=schedule, update_fields=[])


@transaction.atomic
def delete_schedule_block(*, schedule, block, expected_revision):
    schedule = Schedule.objects.select_for_update().get(id=schedule.id)
    block = ScheduleBlock.objects.select_for_update().get(id=block.id, schedule=schedule)
    assert_expected_revision(schedule=schedule, expected_revision=expected_revision)
    block.delete()
    return bump_revision(schedule=schedule, update_fields=[])


@transaction.atomic
def create_schedule_exception(*, company, schedule, data):
    schedule = Schedule.objects.select_for_update().get(id=schedule.id)
    assert_expected_revision(schedule=schedule, expected_revision=data.pop("expected_revision"))
    playlist = None
    if data["action"] == ScheduleException.Action.REPLACE:
        playlist = assert_playlist_schedulable(company=company, playlist_id=data["playlist_id"])
    exception = ScheduleException(
        schedule=schedule,
        date=data["date"],
        start_time=data["start_time"],
        end_time=data["end_time"],
        action=data["action"],
        playlist=playlist,
        priority=data.get("priority", 0),
        volume_override=data.get("volume_override"),
        description=data.get("description", ""),
    )
    exception.full_clean()
    exception.save()
    validate_exception_conflicts(exception=exception)
    return bump_revision(schedule=schedule, update_fields=[])


@transaction.atomic
def update_schedule_exception(*, company, schedule, exception, data):
    schedule = Schedule.objects.select_for_update().get(id=schedule.id)
    exception = ScheduleException.objects.select_for_update().get(id=exception.id, schedule=schedule)
    assert_expected_revision(schedule=schedule, expected_revision=data.pop("expected_revision"))
    if "action" in data:
        exception.action = data["action"]
        exception.playlist = None
        exception.channel = None
    if "playlist_id" in data:
        exception.playlist = assert_playlist_schedulable(company=company, playlist_id=data["playlist_id"]) if data["playlist_id"] else None
    for field in ["date", "start_time", "end_time", "priority", "volume_override", "description"]:
        if field in data:
            setattr(exception, field, data[field])
    if exception.action == ScheduleException.Action.SILENCE:
        exception.playlist = None
        exception.channel = None
    exception.full_clean()
    exception.save()
    validate_exception_conflicts(exception=exception)
    return bump_revision(schedule=schedule, update_fields=[])


@transaction.atomic
def delete_schedule_exception(*, schedule, exception, expected_revision):
    schedule = Schedule.objects.select_for_update().get(id=schedule.id)
    exception = ScheduleException.objects.select_for_update().get(id=exception.id, schedule=schedule)
    assert_expected_revision(schedule=schedule, expected_revision=expected_revision)
    exception.delete()
    return bump_revision(schedule=schedule, update_fields=[])


@transaction.atomic
def create_schedule_assignment(*, company, schedule, data, actor):
    schedule = Schedule.objects.select_for_update().get(id=schedule.id)
    assert_expected_revision(schedule=schedule, expected_revision=data.pop("expected_revision"))
    scope = resolve_scope_from_payload(
        company=company,
        scope_type=data["scope_type"],
        site_id=data.get("site_id"),
        zone_id=data.get("zone_id"),
    )
    assignment = ScheduleAssignment(
        company=company,
        schedule=schedule,
        scope=scope,
        priority=data.get("priority", 0),
        is_locked=data.get("is_locked", False),
        starts_at=data.get("starts_at"),
        ends_at=data.get("ends_at"),
        assigned_by=actor,
        is_active=data.get("is_active", True),
    )
    assignment.full_clean()
    assignment.save()
    validate_assignment_conflicts(assignment=assignment)
    return bump_revision(schedule=schedule, update_fields=[])


@transaction.atomic
def update_schedule_assignment(*, schedule, assignment, data):
    schedule = Schedule.objects.select_for_update().get(id=schedule.id)
    assignment = ScheduleAssignment.objects.select_for_update().get(id=assignment.id, schedule=schedule)
    assert_expected_revision(schedule=schedule, expected_revision=data.pop("expected_revision"))
    for field in ["priority", "is_locked", "starts_at", "ends_at", "is_active"]:
        if field in data:
            setattr(assignment, field, data[field])
    assignment.full_clean()
    assignment.save()
    if assignment.is_active:
        validate_assignment_conflicts(assignment=assignment)
    return bump_revision(schedule=schedule, update_fields=[])


@transaction.atomic
def deactivate_schedule_assignment(*, schedule, assignment, expected_revision):
    schedule = Schedule.objects.select_for_update().get(id=schedule.id)
    assignment = ScheduleAssignment.objects.select_for_update().get(id=assignment.id, schedule=schedule)
    assert_expected_revision(schedule=schedule, expected_revision=expected_revision)
    assignment.is_active = False
    assignment.save(update_fields=["is_active", "updated_at"])
    return bump_revision(schedule=schedule, update_fields=[])


@transaction.atomic
def publish_schedule(*, schedule, expected_revision, published_by=None):
    schedule = Schedule.objects.select_for_update().get(id=schedule.id)
    assert_expected_revision(schedule=schedule, expected_revision=expected_revision)
    if not schedule.blocks.exists():
        raise ScheduleNotPublishable(fields={"blocks": ["La programacion necesita al menos un bloque."]})
    for block in schedule.blocks.select_related("playlist", "channel"):
        if block.content_type == ScheduleBlock.ContentType.PLAYLIST and (
            not block.playlist_id
            or block.playlist.status != Playlist.Status.PUBLISHED
                or not get_latest_published_snapshot(playlist=block.playlist)
        ):
            raise ScheduleNotPublishable(fields={"blocks": ["Todos los bloques PLAYLIST necesitan una playlist publicada."]})
        if block.content_type == ScheduleBlock.ContentType.CHANNEL and (
            not block.channel_id
            or block.channel.status != Channel.Status.PUBLISHED
            or not get_latest_published_channel_snapshot(channel=block.channel)
        ):
            raise ScheduleNotPublishable(fields={"blocks": ["Todos los bloques CHANNEL necesitan un canal publicado."]})
    for block in schedule.blocks.all():
        validate_block_conflicts(block=block)
    for assignment in schedule.assignments.filter(is_active=True):
        validate_assignment_conflicts(assignment=assignment)
    next_version = schedule.version + 1
    snapshot_data = schedule_snapshot_payload(schedule=schedule, version=next_version)
    checksum = schedule_snapshot_checksum(payload=snapshot_data)
    schedule.status = Schedule.Status.PUBLISHED
    schedule.version = next_version
    schedule.published_at = timezone.now()
    ScheduleSnapshot.objects.create(
        schedule=schedule,
        version=next_version,
        checksum=checksum,
        status=ScheduleSnapshot.Status.PUBLISHED,
        timezone=schedule.timezone,
        valid_from=schedule.valid_from,
        valid_until=schedule.valid_until,
        snapshot_data=snapshot_data,
        published_by=published_by,
        published_at=schedule.published_at,
    )
    schedule = bump_revision(schedule=schedule, update_fields=["status", "version", "published_at"])

    from apps.playback.services import create_zone_operational_snapshot

    zones = Zone.objects.filter(company=schedule.company).exclude(
        status=Zone.Status.ARCHIVED
    ).select_related("site", "company")
    for zone in zones:
        effective = resolve_effective_schedule_for_zone(zone=zone, at=timezone.now())
        if effective.get("schedule") and effective["schedule"].id == schedule.id:
            create_zone_operational_snapshot(zone=zone, reason="SCHEDULE_PUBLISHED")
    return schedule


@transaction.atomic
def archive_schedule(*, schedule, expected_revision):
    schedule = Schedule.objects.select_for_update().get(id=schedule.id)
    assert_expected_revision(schedule=schedule, expected_revision=expected_revision)
    schedule.status = Schedule.Status.ARCHIVED
    schedule.assignments.filter(is_active=True).update(is_active=False, updated_at=timezone.now())
    return bump_revision(schedule=schedule, update_fields=["status"])


@transaction.atomic
def reactivate_schedule(*, schedule, expected_revision):
    schedule = Schedule.objects.select_for_update().get(id=schedule.id)
    assert_expected_revision(schedule=schedule, expected_revision=expected_revision)
    schedule.status = Schedule.Status.DRAFT
    return bump_revision(schedule=schedule, update_fields=["status"])


@transaction.atomic
def disable_schedule(*, schedule, expected_revision):
    schedule = Schedule.objects.select_for_update().get(id=schedule.id)
    assert_expected_revision(schedule=schedule, expected_revision=expected_revision)
    schedule.status = Schedule.Status.DISABLED
    schedule.assignments.filter(is_active=True).update(is_active=False, updated_at=timezone.now())
    return bump_revision(schedule=schedule, update_fields=["status"])


def resolve_effective_schedule(*, zone, at=None):
    at = at or timezone.now()
    specificity = {
        "COMPANY": 1,
        "ORGANIZATIONAL_UNIT": 2,
        "RESOURCE_GROUP": 3,
        "SITE": 4,
        "ZONE": 5,
    }
    assignments = zone.company.schedule_assignments.filter(is_active=True).select_related("schedule", "scope")
    assignments = [
        assignment
        for assignment in assignments
        if (assignment.starts_at is None or assignment.starts_at <= at)
        and (assignment.ends_at is None or assignment.ends_at > at)
    ]
    return sorted(
        assignments,
        key=lambda assignment: (
            assignment.is_locked,
            assignment.priority,
            specificity.get(assignment.scope.scope_type, 0),
            assignment.created_at,
        ),
        reverse=True,
    )[0] if assignments else None
