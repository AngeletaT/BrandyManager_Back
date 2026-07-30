from django.db import transaction
from django.utils import timezone

from apps.billing.models import License, LicenseAssignment


@transaction.atomic
def assign_license_to_zone(*, license_id, zone, assigned_by=None, reason=""):
    license_obj = License.objects.select_for_update().get(id=license_id)
    LicenseAssignment.objects.select_for_update().filter(zone=zone, unassigned_at__isnull=True)

    assignment = LicenseAssignment.objects.create(
        company=license_obj.company,
        license=license_obj,
        zone=zone,
        assigned_by=assigned_by,
        assigned_at=timezone.now(),
        reason=reason,
    )
    license_obj.status = License.Status.ASSIGNED
    license_obj.activated_at = license_obj.activated_at or assignment.assigned_at
    license_obj.save(update_fields=["status", "activated_at", "updated_at"])
    return assignment


@transaction.atomic
def unassign_license(*, assignment_id, unassigned_by=None, reason=""):
    assignment = LicenseAssignment.objects.select_for_update().select_related("license").get(id=assignment_id)
    if assignment.unassigned_at:
        return assignment

    assignment.unassigned_at = timezone.now()
    assignment.unassigned_by = unassigned_by
    assignment.reason = reason or assignment.reason
    assignment.save(update_fields=["unassigned_at", "unassigned_by", "reason"])

    license_obj = assignment.license
    license_obj.status = License.Status.AVAILABLE
    license_obj.save(update_fields=["status", "updated_at"])
    return assignment
