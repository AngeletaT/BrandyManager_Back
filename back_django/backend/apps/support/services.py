from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.organizations.models import CompanyMembership
from apps.organizations.selectors import membership_has_active_role
from apps.support.models import Incident, IncidentEvent


INCIDENT_TYPE_MEMBERSHIP_TRANSFER_REQUEST = "MEMBERSHIP_TRANSFER_REQUEST"


@transaction.atomic
def create_membership_transfer_request(
    *,
    owner_membership,
    membership_to_transfer,
    target_company,
    requested_by,
    reason,
):
    if owner_membership.status != CompanyMembership.Status.ACTIVE:
        raise ValidationError("La solicitud debe realizarla un owner activo.")
    if owner_membership.user_id != requested_by.id:
        raise ValidationError("El usuario solicitante debe coincidir con la membresia owner.")
    if owner_membership.company_id != membership_to_transfer.company_id:
        raise ValidationError("El owner solo puede solicitar cambios sobre su empresa.")
    if not membership_has_active_role(membership=owner_membership, role_code="OWNER"):
        raise ValidationError("La solicitud requiere rol OWNER activo.")
    if target_company.id == membership_to_transfer.company_id:
        raise ValidationError("La empresa destino debe ser distinta.")

    now = timezone.now()
    incident = Incident.objects.create(
        company=owner_membership.company,
        incident_type=INCIDENT_TYPE_MEMBERSHIP_TRANSFER_REQUEST,
        severity=Incident.Severity.MEDIUM,
        title="Solicitud de transferencia de usuario entre empresas",
        description=reason,
        detected_by=Incident.DetectedBy.USER,
        detected_at=now,
        metadata={
            "requested_by_user_id": str(requested_by.id),
            "membership_id": str(membership_to_transfer.id),
            "user_id": str(membership_to_transfer.user_id),
            "source_company_id": str(membership_to_transfer.company_id),
            "target_company_id": str(target_company.id),
        },
    )
    IncidentEvent.objects.create(
        incident=incident,
        actor_user=requested_by,
        event_type=IncidentEvent.EventType.CREATED,
        message="Solicitud creada por owner para revision interna.",
    )
    return incident
