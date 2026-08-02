from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.services import register_audit_log
from apps.organizations.models import CompanyMembership, MembershipGrant, MembershipPermissionOverride
from apps.support.services import INCIDENT_TYPE_MEMBERSHIP_TRANSFER_REQUEST


def user_can_perform_internal_support_action(*, user):
    return user.platform_roles.filter(revoked_at__isnull=True, role__is_active=True).exists()


@transaction.atomic
def transfer_membership_by_support_ticket(
    *,
    membership,
    target_company,
    support_incident,
    performed_by,
    reason,
):
    if not user_can_perform_internal_support_action(user=performed_by):
        raise ValidationError("Solo un administrador interno puede ejecutar esta operacion.")
    if support_incident.incident_type != INCIDENT_TYPE_MEMBERSHIP_TRANSFER_REQUEST:
        raise ValidationError("La incidencia no corresponde a una transferencia de membresia.")
    if support_incident.status not in {
        support_incident.Status.OPEN,
        support_incident.Status.ACKNOWLEDGED,
        support_incident.Status.INVESTIGATING,
    }:
        raise ValidationError("La incidencia no esta en un estado operable.")

    membership = CompanyMembership.objects.select_for_update().select_related("company", "user").get(pk=membership.pk)
    source_company = membership.company
    expected_metadata = support_incident.metadata or {}
    if expected_metadata.get("membership_id") != str(membership.id):
        raise ValidationError("La incidencia no corresponde a esta membresia.")
    if expected_metadata.get("source_company_id") != str(source_company.id):
        raise ValidationError("La empresa origen no coincide con la incidencia.")
    if expected_metadata.get("target_company_id") != str(target_company.id):
        raise ValidationError("La empresa destino no coincide con la incidencia.")
    if target_company.id == source_company.id:
        raise ValidationError("La empresa destino debe ser distinta.")

    now = timezone.now()
    before_data = {
        "membership_id": str(membership.id),
        "user_id": str(membership.user_id),
        "company_id": str(source_company.id),
        "status": membership.status,
    }

    MembershipGrant.objects.select_for_update().filter(
        membership=membership,
        is_active=True,
    ).update(is_active=False, ends_at=now, updated_at=now)
    MembershipPermissionOverride.objects.select_for_update().filter(
        membership=membership,
        ends_at__isnull=True,
    ).update(ends_at=now, updated_at=now)

    membership.company = target_company
    membership.status = CompanyMembership.Status.INVITED
    membership.invited_by = None
    membership.invited_at = now
    membership.accepted_at = None
    membership.last_access_at = None
    membership.save(
        update_fields=[
            "company",
            "status",
            "invited_by",
            "invited_at",
            "accepted_at",
            "last_access_at",
            "updated_at",
        ]
    )

    support_incident.status = support_incident.Status.RESOLVED
    support_incident.resolved_at = now
    support_incident.assigned_to = performed_by
    support_incident.save(update_fields=["status", "resolved_at", "assigned_to", "updated_at"])

    after_data = {
        "membership_id": str(membership.id),
        "user_id": str(membership.user_id),
        "company_id": str(target_company.id),
        "status": membership.status,
        "support_incident_id": str(support_incident.id),
        "reason": reason,
    }
    register_audit_log(
        action="company_membership.transfer_by_support_ticket",
        entity_type="CompanyMembership",
        company=target_company,
        actor_user=performed_by,
        entity_id=membership.id,
        entity_label=membership.user.email,
        before_data=before_data,
        after_data=after_data,
    )
    return membership
