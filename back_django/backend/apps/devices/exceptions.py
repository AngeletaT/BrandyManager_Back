from rest_framework import status

from shared.api.exceptions import DomainError


class DeviceNotFound(DomainError):
    def __init__(self):
        super().__init__(
            code="device_not_found",
            message="El dispositivo no existe o no esta disponible.",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class DeviceLimitReached(DomainError):
    def __init__(self):
        super().__init__(
            code="device_limit_reached",
            message="Has alcanzado el limite de dispositivos de tu plan.",
            fields={"devices": ["Limite alcanzado."]},
            status_code=status.HTTP_403_FORBIDDEN,
        )


class DeviceCodeConflict(DomainError):
    def __init__(self):
        super().__init__(
            code="device_code_conflict",
            message="Ya existe un dispositivo con este codigo en la empresa.",
            fields={"code": ["Ya existe un dispositivo con este codigo."]},
            status_code=status.HTTP_409_CONFLICT,
        )


class DeviceRevisionConflict(DomainError):
    def __init__(self):
        super().__init__(
            code="device_revision_conflict",
            message="El dispositivo ha cambiado. Recarga los datos antes de guardar.",
            status_code=status.HTTP_409_CONFLICT,
        )


class DeviceZoneInvalid(DomainError):
    def __init__(self, *, message="La zona indicada no es valida para el dispositivo."):
        super().__init__(
            code="device_zone_invalid",
            message=message,
            fields={"zone_id": [message]},
            status_code=status.HTTP_400_BAD_REQUEST,
        )


class DeviceActivationInvalid(DomainError):
    def __init__(self):
        super().__init__(
            code="device_activation_invalid",
            message="El codigo de activacion no es valido o ha caducado.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )


class DeviceActivationRateLimited(DomainError):
    def __init__(self):
        super().__init__(
            code="device_activation_rate_limited",
            message="Se han realizado demasiados intentos. Espera antes de volver a intentarlo.",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        )


class DeviceSessionExpired(DomainError):
    def __init__(self):
        super().__init__(
            code="device_session_expired",
            message="La sesion del dispositivo ha caducado.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )


class DeviceCredentialRevoked(DomainError):
    def __init__(self):
        super().__init__(
            code="device_credential_revoked",
            message="La credencial del dispositivo ha sido revocada.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )


class PlaybackCommandInvalid(DomainError):
    def __init__(self, *, fields=None):
        super().__init__(
            code="playback_command_invalid",
            message="El comando de reproduccion no es valido.",
            fields=fields or {},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
