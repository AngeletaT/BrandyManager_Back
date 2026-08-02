from urllib.parse import urlencode

from django.conf import settings

from shared.email.services import send_plain_email


def build_email_verification_url(*, raw_token):
    query = urlencode({"token": raw_token})
    return f"{settings.FRONTEND_BASE_URL}/verificar-email?{query}"


def send_email_verification_email(*, user, raw_token):
    verification_url = build_email_verification_url(raw_token=raw_token)
    body = (
        f"Hola {user.first_name or user.email},\n\n"
        "Confirma tu correo para activar tu cuenta de BrandyManager:\n"
        f"{verification_url}\n\n"
        "Si no has creado esta cuenta, puedes ignorar este mensaje."
    )
    return send_plain_email(
        to=user.email,
        subject="Verifica tu correo en BrandyManager",
        body=body,
    )


def build_password_reset_url(*, raw_token):
    query = urlencode({"token": raw_token})
    return f"{settings.FRONTEND_BASE_URL}/reset-password?{query}"


def send_password_reset_email(*, user, raw_token):
    reset_url = build_password_reset_url(raw_token=raw_token)
    body = (
        f"Hola {user.first_name or user.email},\n\n"
        "Puedes cambiar tu contrasena de BrandyManager desde este enlace:\n"
        f"{reset_url}\n\n"
        "Si no has solicitado este cambio, puedes ignorar este mensaje."
    )
    return send_plain_email(
        to=user.email,
        subject="Restablece tu contrasena de BrandyManager",
        body=body,
    )
