from django.db import transaction
from django.utils import timezone

from apps.devices.models import DeviceCommand, DeviceZoneAssignment


@transaction.atomic
def assign_device_to_zone(*, device, zone, assigned_by=None, assignment_role=DeviceZoneAssignment.AssignmentRole.PRIMARY, reason=""):
    DeviceZoneAssignment.objects.select_for_update().filter(device=device, unassigned_at__isnull=True)
    if assignment_role == DeviceZoneAssignment.AssignmentRole.PRIMARY:
        DeviceZoneAssignment.objects.select_for_update().filter(zone=zone, assignment_role=assignment_role, unassigned_at__isnull=True)
    return DeviceZoneAssignment.objects.create(
        company=device.company,
        device=device,
        zone=zone,
        assignment_role=assignment_role,
        assigned_by=assigned_by,
        assigned_at=timezone.now(),
        reason=reason,
    )


@transaction.atomic
def replace_zone_device(*, old_assignment, new_device, assigned_by=None, reason=""):
    old_assignment = DeviceZoneAssignment.objects.select_for_update().get(id=old_assignment.id)
    old_assignment.unassigned_at = timezone.now()
    old_assignment.unassigned_by = assigned_by
    old_assignment.reason = reason or old_assignment.reason
    old_assignment.save(update_fields=["unassigned_at", "unassigned_by", "reason"])
    return assign_device_to_zone(
        device=new_device,
        zone=old_assignment.zone,
        assigned_by=assigned_by,
        assignment_role=old_assignment.assignment_role,
        reason=reason,
    )


def create_device_command(*, device, command_type, payload=None, created_by=None, expires_at=None):
    return DeviceCommand.objects.create(
        company=device.company,
        device=device,
        command_type=command_type,
        payload=payload or {},
        created_by=created_by,
        expires_at=expires_at,
    )
