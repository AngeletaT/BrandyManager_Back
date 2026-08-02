from rest_framework import status

from shared.api.exceptions import DomainError


class OnboardingAlreadyCompleted(DomainError):
    def __init__(self):
        super().__init__(
            code="onboarding_already_completed",
            message="El alta de empresa ya esta completada para este usuario.",
            status_code=status.HTTP_409_CONFLICT,
        )


class OnboardingNotAllowed(DomainError):
    def __init__(self):
        super().__init__(
            code="onboarding_not_allowed",
            message="Este usuario no puede completar el alta de una cuenta cliente.",
            status_code=status.HTTP_403_FORBIDDEN,
        )


class CompanyTaxIdAlreadyRegistered(DomainError):
    def __init__(self):
        super().__init__(
            code="company_tax_id_already_registered",
            message="Ya existe una cuenta empresarial con este identificador fiscal.",
            fields={"tax_id": ["Ya existe una empresa con este identificador fiscal."]},
            status_code=status.HTTP_409_CONFLICT,
        )


class OnboardingConfigurationMissing(DomainError):
    def __init__(self):
        super().__init__(
            code="onboarding_configuration_missing",
            message="La configuracion inicial de onboarding no esta disponible.",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
