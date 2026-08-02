from rest_framework import status

from shared.api.exceptions import DomainError


class EmailAlreadyRegistered(DomainError):
    def __init__(self):
        super().__init__(
            code="email_already_registered",
            message="Ya existe una cuenta con este email.",
            fields={"email": ["Ya existe una cuenta con este email."]},
            status_code=status.HTTP_409_CONFLICT,
        )


class VerificationTokenInvalid(DomainError):
    def __init__(self):
        super().__init__(
            code="verification_token_invalid",
            message="El enlace de verificacion no es valido o ha caducado.",
            fields={"token": ["El token no es valido."]},
            status_code=status.HTTP_400_BAD_REQUEST,
        )


class PasswordResetTokenInvalid(DomainError):
    def __init__(self):
        super().__init__(
            code="password_reset_token_invalid",
            message="El enlace de recuperacion no es valido o ha caducado.",
            fields={"token": ["El token no es valido."]},
            status_code=status.HTTP_400_BAD_REQUEST,
        )


class EmailNotVerified(DomainError):
    def __init__(self):
        super().__init__(
            code="email_not_verified",
            message="Debes verificar tu correo antes de iniciar sesion.",
            extra={"next_step": "VERIFY_EMAIL"},
            status_code=status.HTTP_403_FORBIDDEN,
        )


class InvalidCredentials(DomainError):
    def __init__(self):
        super().__init__(
            code="invalid_credentials",
            message="Credenciales incorrectas.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )


class UserInactive(DomainError):
    def __init__(self):
        super().__init__(
            code="user_inactive",
            message="El usuario esta desactivado.",
            status_code=status.HTTP_403_FORBIDDEN,
        )


class SessionExpired(DomainError):
    def __init__(self):
        super().__init__(
            code="session_expired",
            message="La sesion ha caducado.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )


class OriginNotTrusted(DomainError):
    def __init__(self):
        super().__init__(
            code="origin_not_trusted",
            message="El origen de la peticion no esta autorizado.",
            status_code=status.HTTP_403_FORBIDDEN,
        )
