from urllib.parse import urlencode

from django.conf import settings

from shared.email.services import send_plain_email


def build_company_invitation_url(*, raw_token):
    query = urlencode({"token": raw_token})
    return f"{settings.FRONTEND_BASE_URL}/invitacion?{query}"


def send_company_invitation_email(*, invitation, raw_token):
    invitation_url = build_company_invitation_url(raw_token=raw_token)
    invited_name = invitation.first_name or invitation.invited_email
    body = (
        f"Hola {invited_name},\n\n"
        f"Te han invitado a unirte a {invitation.company.trade_name} en BrandyManager.\n\n"
        f"Completa la invitacion desde este enlace:\n{invitation_url}\n\n"
        "Si no esperabas este correo, puedes ignorarlo."
    )
    return send_plain_email(
        to=invitation.invited_email,
        subject="Invitacion a BrandyManager",
        body=body,
    )
