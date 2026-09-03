from rest_framework import status

from shared.api.exceptions import DomainError


class PlanLimitReached(DomainError):
    def __init__(self, *, limit_key):
        super().__init__(
            code="plan_limit_reached",
            message="Has alcanzado el limite de tu plan.",
            fields={limit_key: ["Limite alcanzado."]},
            status_code=status.HTTP_403_FORBIDDEN,
        )


class SiteNotFound(DomainError):
    def __init__(self):
        super().__init__(
            code="site_not_found",
            message="La sede no existe o no esta disponible.",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class SiteCodeConflict(DomainError):
    def __init__(self):
        super().__init__(
            code="site_code_conflict",
            message="Ya existe una sede con este codigo en la empresa.",
            fields={"code": ["Ya existe una sede con este codigo."]},
            status_code=status.HTTP_409_CONFLICT,
        )


class ZoneNotFound(DomainError):
    def __init__(self):
        super().__init__(
            code="zone_not_found",
            message="La zona no existe o no esta disponible.",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class ZoneCodeConflict(DomainError):
    def __init__(self):
        super().__init__(
            code="zone_code_conflict",
            message="Ya existe una zona con este codigo en la sede.",
            fields={"code": ["Ya existe una zona con este codigo en la sede."]},
            status_code=status.HTTP_409_CONFLICT,
        )


class SiteArchived(DomainError):
    def __init__(self):
        super().__init__(
            code="site_archived",
            message="La sede esta archivada y no permite operar zonas.",
            status_code=status.HTTP_409_CONFLICT,
        )


class MembershipNotFound(DomainError):
    def __init__(self):
        super().__init__(
            code="membership_not_found",
            message="La membresia no existe o no esta disponible.",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class ProtectedOwner(DomainError):
    def __init__(self):
        super().__init__(
            code="protected_owner",
            message="El owner de la cuenta no puede modificarse desde este flujo.",
            status_code=status.HTTP_403_FORBIDDEN,
        )


class InvalidRoleAssignment(DomainError):
    def __init__(self):
        super().__init__(
            code="invalid_role_assignment",
            message="El rol solicitado no puede asignarse.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )


class InvitationConflict(DomainError):
    def __init__(self, *, code="invitation_conflict", message="No se puede crear la invitacion solicitada.", fields=None):
        super().__init__(
            code=code,
            message=message,
            fields=fields or {},
            status_code=status.HTTP_409_CONFLICT,
        )


class InvitationNotFound(DomainError):
    def __init__(self):
        super().__init__(
            code="invitation_not_found",
            message="La invitacion no existe o no esta disponible.",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class InvitationTokenInvalid(DomainError):
    def __init__(self):
        super().__init__(
            code="invitation_token_invalid",
            message="La invitacion no es valida o ha caducado.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )


class InvitationRateLimited(DomainError):
    def __init__(self):
        super().__init__(
            code="invitation_resend_rate_limited",
            message="La invitacion se ha reenviado recientemente.",
            status_code=status.HTTP_202_ACCEPTED,
        )


class CompanyTaxIdConflict(DomainError):
    def __init__(self):
        super().__init__(
            code="company_tax_id_already_registered",
            message="Ya existe una empresa registrada con este identificador fiscal.",
            fields={"tax_id": ["Ya existe una empresa con este identificador fiscal."]},
            status_code=status.HTTP_409_CONFLICT,
        )
