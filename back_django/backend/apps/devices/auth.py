import jwt
from django.conf import settings
from django.utils import timezone
from rest_framework import authentication
from rest_framework.exceptions import AuthenticationFailed

from apps.devices.models import Device, DeviceCredential


class DevicePrincipal:
    is_authenticated = True
    is_anonymous = False

    def __init__(self, *, device, credential):
        self.device = device
        self.credential = credential
        self.pk = device.pk


def issue_device_access_token(*, device, credential):
    now = timezone.now()
    expires_at = now + settings.BM_DEVICE_ACCESS_TOKEN_LIFETIME
    payload = {
        "iss": settings.BM_DEVICE_JWT_ISSUER,
        "aud": settings.BM_DEVICE_JWT_AUDIENCE,
        "typ": "bm_device_access",
        "sub": str(device.id),
        "device_id": str(device.id),
        "credential_id": credential.credential_id,
        "company_id": str(device.company_id),
        "zone_id": str(device.zone_id) if device.zone_id else None,
        "iat": now,
        "exp": expires_at,
    }
    token = jwt.encode(payload, settings.BM_DEVICE_JWT_SIGNING_KEY, algorithm="HS256")
    return token, int(settings.BM_DEVICE_ACCESS_TOKEN_LIFETIME.total_seconds())


def _authenticate_device_payload(*, token):
    try:
        payload = jwt.decode(
            token,
            settings.BM_DEVICE_JWT_SIGNING_KEY,
            algorithms=["HS256"],
            audience=settings.BM_DEVICE_JWT_AUDIENCE,
            issuer=settings.BM_DEVICE_JWT_ISSUER,
            options={"require": ["exp", "iat", "sub", "aud", "iss"]},
        )
    except jwt.PyJWTError as exc:
        raise AuthenticationFailed("La credencial del dispositivo no es valida.", code="device_access_invalid") from exc
    if payload.get("typ") != "bm_device_access":
        raise AuthenticationFailed("La credencial del dispositivo no es valida.", code="device_access_invalid")
    return payload


def authenticate_device_access_token(*, token):
    payload = _authenticate_device_payload(token=token)
    credential = (
        DeviceCredential.objects.select_related("device", "device__company", "device__zone")
        .filter(credential_id=payload.get("credential_id"))
        .first()
    )
    now = timezone.now()
    if (
        not credential
        or str(credential.device_id) != payload.get("device_id")
        or credential.status != DeviceCredential.Status.ACTIVE
        or (credential.expires_at and credential.expires_at <= now)
        or credential.device.activation_status != Device.ActivationStatus.ACTIVATED
        or credential.device.administrative_status != Device.AdministrativeStatus.ACTIVE
    ):
        raise AuthenticationFailed("La credencial del dispositivo no es valida.", code="device_access_invalid")
    credential.last_used_at = now
    credential.save(update_fields=["last_used_at"])
    return DevicePrincipal(device=credential.device, credential=credential), payload


class DeviceJWTAuthentication(authentication.BaseAuthentication):
    keyword = "Bearer"

    def authenticate(self, request):
        authorization = authentication.get_authorization_header(request).split()
        if not authorization:
            return None
        if len(authorization) != 2 or authorization[0].decode("ascii", "ignore").lower() != self.keyword.lower():
            raise AuthenticationFailed("Cabecera de autorizacion no valida.")
        principal, _ = authenticate_device_access_token(token=authorization[1].decode("utf-8"))
        return principal, None

    def authenticate_header(self, request):
        return self.keyword
