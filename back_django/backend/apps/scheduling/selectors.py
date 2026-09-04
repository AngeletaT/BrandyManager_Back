from datetime import date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from django.db.models import Count, Q
from django.utils import timezone

from apps.authorization.services import get_company_scope, membership_has_permission, site_ids_accessible_by_membership, zone_ids_accessible_by_membership
from apps.organizations.models import ResourceScope, Site, Zone
from apps.scheduling.models import Schedule, ScheduleAssignment, ScheduleBlock, ScheduleException


SCHEDULE_ORDERING_FIELDS = {
    "name": "name",
    "-name": "-name",
    "created_at": "created_at",
    "-created_at": "-created_at",
    "updated_at": "updated_at",
    "-updated_at": "-updated_at",
    "published_at": "published_at",
    "-published_at": "-published_at",
}

SCOPE_SPECIFICITY = {
    ResourceScope.ScopeType.COMPANY: 1,
    ResourceScope.ScopeType.ORGANIZATIONAL_UNIT: 2,
    ResourceScope.ScopeType.RESOURCE_GROUP: 3,
    ResourceScope.ScopeType.SITE: 4,
    ResourceScope.ScopeType.ZONE: 5,
}


def _as_uuid(value):
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def list_schedules_for_membership(
    *,
    membership,
    permission_code="schedules.view",
    search="",
    status_value="",
    scope_type="",
    site_id=None,
    zone_id=None,
    ordering="name",
):
    company = membership.company
    queryset = (
        Schedule.objects.filter(company=company)
        .annotate(block_count=Count("blocks", distinct=True), assignment_count=Count("assignments", distinct=True))
        .prefetch_related("assignments__scope", "assignments__scope__site", "assignments__scope__zone")
    )

    company_scope = get_company_scope(company=company)
    if not membership_has_permission(membership=membership, permission_code=permission_code, scope=company_scope):
        site_ids = site_ids_accessible_by_membership(membership=membership, permission_code=permission_code)
        zone_ids = zone_ids_accessible_by_membership(membership=membership, permission_code=permission_code)
        scope_filter = Q(assignments__scope__scope_type=ResourceScope.ScopeType.ZONE, assignments__scope__zone_id__in=zone_ids)
        if site_ids:
            scope_filter |= Q(assignments__scope__scope_type=ResourceScope.ScopeType.SITE, assignments__scope__site_id__in=site_ids)
            scope_filter |= Q(assignments__scope__scope_type=ResourceScope.ScopeType.ZONE, assignments__scope__zone__site_id__in=site_ids)
        queryset = queryset.filter(assignments__is_active=True).filter(scope_filter)

    search = (search or "").strip()
    if search:
        queryset = queryset.filter(Q(name__icontains=search) | Q(description__icontains=search) | Q(timezone__icontains=search))
    status_value = (status_value or "").strip()
    if status_value:
        queryset = queryset.filter(status=status_value)
    scope_type = (scope_type or "").strip()
    if scope_type:
        queryset = queryset.filter(assignments__scope__scope_type=scope_type)
    if site_id:
        queryset = queryset.filter(assignments__scope__site_id=site_id)
    if zone_id:
        queryset = queryset.filter(assignments__scope__zone_id=zone_id)

    return queryset.order_by(SCHEDULE_ORDERING_FIELDS.get(ordering, "name"), "id").distinct()


def get_schedule_for_membership(*, membership, schedule_id, permission_code="schedules.view"):
    schedule_uuid = _as_uuid(schedule_id)
    if not schedule_uuid:
        return None
    return (
        list_schedules_for_membership(membership=membership, permission_code=permission_code)
        .filter(id=schedule_uuid)
        .select_related("company", "created_by")
        .prefetch_related(
            "blocks__playlist",
            "blocks__playlist__snapshots",
            "exceptions__playlist",
            "exceptions__playlist__snapshots",
            "assignments__scope",
            "assignments__scope__site",
            "assignments__scope__zone",
        )
        .first()
    )


def get_schedule_block(*, schedule, block_id):
    block_uuid = _as_uuid(block_id)
    if not block_uuid:
        return None
    return schedule.blocks.select_related("playlist").filter(id=block_uuid).first()


def get_schedule_exception(*, schedule, exception_id):
    exception_uuid = _as_uuid(exception_id)
    if not exception_uuid:
        return None
    return schedule.exceptions.select_related("playlist").filter(id=exception_uuid).first()


def get_schedule_assignment(*, schedule, assignment_id):
    assignment_uuid = _as_uuid(assignment_id)
    if not assignment_uuid:
        return None
    return schedule.assignments.select_related("scope", "scope__site", "scope__zone").filter(id=assignment_uuid).first()


def list_relevant_scopes_for_zone(*, zone):
    return list(
        ResourceScope.objects.filter(company=zone.company).filter(
            Q(scope_type=ResourceScope.ScopeType.COMPANY)
            | Q(scope_type=ResourceScope.ScopeType.SITE, site=zone.site)
            | Q(scope_type=ResourceScope.ScopeType.ZONE, zone=zone)
        )
    )


def assignment_applies_at(*, assignment, at):
    return (
        assignment.is_active
        and (assignment.starts_at is None or assignment.starts_at <= at)
        and (assignment.ends_at is None or assignment.ends_at > at)
    )


def schedule_applies_on_date(*, schedule, local_date):
    return (
        schedule.status == Schedule.Status.PUBLISHED
        and (schedule.valid_from is None or schedule.valid_from <= local_date)
        and (schedule.valid_until is None or schedule.valid_until >= local_date)
    )


def time_ranges_overlap(start_a, end_a, start_b, end_b):
    return start_a < end_b and start_b < end_a


def list_assignment_conflicts(*, assignment):
    return list(
        ScheduleAssignment.objects.filter(
            company=assignment.company,
            scope=assignment.scope,
            is_active=True,
            priority=assignment.priority,
        )
        .exclude(id=assignment.id)
        .filter(
            Q(starts_at__isnull=True) | Q(starts_at__lt=assignment.ends_at) if assignment.ends_at else Q(),
            Q(ends_at__isnull=True) | Q(ends_at__gt=assignment.starts_at) if assignment.starts_at else Q(),
        )
        .select_related("schedule", "scope")
    )


def list_block_conflicts(*, block):
    return [
        other
        for other in block.schedule.blocks.filter(day_of_week=block.day_of_week, priority=block.priority).exclude(id=block.id)
        if time_ranges_overlap(block.start_time, block.end_time, other.start_time, other.end_time)
    ]


def list_exception_conflicts(*, exception):
    return [
        other
        for other in exception.schedule.exceptions.filter(date=exception.date, priority=exception.priority).exclude(id=exception.id)
        if time_ranges_overlap(exception.start_time, exception.end_time, other.start_time, other.end_time)
    ]


def ordered_assignments_for_zone_at(*, zone, at):
    scopes = list_relevant_scopes_for_zone(zone=zone)
    scope_by_id = {scope.id: scope for scope in scopes}
    candidates = []
    for assignment in (
        ScheduleAssignment.objects.filter(company=zone.company, scope__in=scopes, is_active=True)
        .select_related("schedule", "scope", "scope__site", "scope__zone")
        .order_by("-is_locked", "-priority", "-created_at")
    ):
        if not assignment_applies_at(assignment=assignment, at=at):
            continue
        local_date = timezone.localtime(at, ZoneInfo(assignment.schedule.timezone)).date()
        if not schedule_applies_on_date(schedule=assignment.schedule, local_date=local_date):
            continue
        candidates.append(assignment)
    return sorted(
        candidates,
        key=lambda item: (
            item.is_locked,
            item.priority,
            SCOPE_SPECIFICITY.get(scope_by_id[item.scope_id].scope_type, 0),
            item.created_at,
        ),
        reverse=True,
    )


def resolve_effective_schedule_for_zone(*, zone, at):
    assignments = ordered_assignments_for_zone_at(zone=zone, at=at)
    if not assignments:
        return {"assignment": None, "schedule": None, "exception": None, "block": None, "content_kind": "NONE"}

    for assignment in assignments:
        schedule = assignment.schedule
        local_dt = timezone.localtime(at, ZoneInfo(schedule.timezone))
        local_time = local_dt.time().replace(tzinfo=None)
        exception = (
            ScheduleException.objects.filter(schedule=schedule, date=local_dt.date(), start_time__lte=local_time, end_time__gt=local_time)
            .select_related("playlist")
            .order_by("-priority", "-created_at")
            .first()
        )
        if exception:
            return {"assignment": assignment, "schedule": schedule, "exception": exception, "block": None, "content_kind": exception.action}
        block = (
            ScheduleBlock.objects.filter(schedule=schedule, day_of_week=local_dt.weekday(), start_time__lte=local_time, end_time__gt=local_time)
            .select_related("playlist")
            .order_by("-priority", "-created_at")
            .first()
        )
        if block:
            return {"assignment": assignment, "schedule": schedule, "exception": None, "block": block, "content_kind": block.content_type}

    return {"assignment": assignments[0], "schedule": assignments[0].schedule, "exception": None, "block": None, "content_kind": "NONE"}


def list_next_occurrences(*, schedule, start_at, days=14, limit=20):
    tz = ZoneInfo(schedule.timezone)
    cursor_date = timezone.localtime(start_at, tz).date()
    end_date = cursor_date + timedelta(days=days)
    occurrences = []
    current = cursor_date
    while current <= end_date and len(occurrences) < limit:
        if schedule.valid_from and current < schedule.valid_from:
            current += timedelta(days=1)
            continue
        if schedule.valid_until and current > schedule.valid_until:
            break
        for block in schedule.blocks.filter(day_of_week=current.weekday()).select_related("playlist").order_by("start_time", "-priority"):
            starts_at = datetime.combine(current, block.start_time, tzinfo=tz)
            ends_at = datetime.combine(current, block.end_time, tzinfo=tz)
            if ends_at <= start_at:
                continue
            occurrences.append({"kind": "BLOCK", "block": block, "exception": None, "starts_at": starts_at, "ends_at": ends_at})
            if len(occurrences) >= limit:
                break
        for exception in schedule.exceptions.filter(date=current).select_related("playlist").order_by("start_time", "-priority"):
            starts_at = datetime.combine(current, exception.start_time, tzinfo=tz)
            ends_at = datetime.combine(current, exception.end_time, tzinfo=tz)
            if ends_at <= start_at:
                continue
            occurrences.append({"kind": "EXCEPTION", "block": None, "exception": exception, "starts_at": starts_at, "ends_at": ends_at})
            if len(occurrences) >= limit:
                break
        current += timedelta(days=1)
    return sorted(occurrences, key=lambda item: item["starts_at"])[:limit]

