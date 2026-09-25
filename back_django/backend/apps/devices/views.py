import hashlib

from django.conf import settings
from django.core.cache import cache
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authorization.services import (
    get_or_create_zone_scope,
    membership_has_permission_on_any_scope,
    require_company_permission,
)
from apps.billing.selectors import get_current_subscription_for_company
from apps.devices.auth import DeviceJWTAuthentication, authenticate_device_access_token, issue_device_access_token
from apps.devices.cookies import clear_device_refresh_cookie, set_device_refresh_cookie
from apps.devices.exceptions import DeviceActivationRateLimited, DeviceNotFound
from apps.devices.models import Device
from apps.devices.selectors import (
    get_device_for_membership,
    list_device_commands,
    list_device_events,
    list_devices_for_membership,
)
from apps.devices.service_auth import HasGoServiceToken
from apps.devices.serializers import (
    DeviceActivationCompleteSerializer,
    DeviceActivationValidateSerializer,
    DeviceCommandCreateSerializer,
    DeviceCommandSerializer,
    DeviceCreateSerializer,
    DeviceEventSerializer,
    DeviceExpectedRevisionSerializer,
    DeviceSerializer,
    DeviceUpdateSerializer,
    DeviceZoneUpdateSerializer,
)
from apps.devices.services import (
    change_device_zone,
    complete_device_activation,
    create_device,
    create_device_command,
    generate_device_activation_code,
    revoke_device,
    revoke_device_credential_from_cookie,
    rotate_device_credential,
    set_device_administrative_status,
    update_device,
    validate_device_activation_code,
)


def _parse_positive_int(value, default, *, field, maximum=None):
    try:
        parsed = int(value or default)
    except (TypeError, ValueError) as exc:
        raise ValidationError({field: ["Debe ser un numero entero positivo."]}) from exc
    if parsed < 1:
        raise ValidationError({field: ["Debe ser un numero entero positivo."]})
    return min(parsed, maximum) if maximum else parsed


def _paginated_response(*, queryset, request, membership, serializer_class=DeviceSerializer):
    page = _parse_positive_int(request.query_params.get("page"), 1, field="page")
    page_size = _parse_positive_int(request.query_params.get("page_size"), 20, field="page_size", maximum=100)
    count = queryset.count()
    return Response(
        {
            "count": count,
            "page": page,
            "page_size": page_size,
            "results": serializer_class(
                queryset[(page - 1) * page_size : page * page_size],
                many=True,
                context={"membership": membership},
            ).data,
        }
    )


def _device_for_permission_or_raise(*, request, device_id, permission_code):
    membership = require_company_permission(user=request.user, permission_code=permission_code)
    device = get_device_for_membership(membership=membership, device_id=device_id)
    if not device:
        raise DeviceNotFound()
    require_company_permission(
        user=request.user,
        permission_code=permission_code,
        scope=get_or_create_zone_scope(zone=device.zone),
    )
    return membership, device


def _client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return forwarded.split(",", 1)[0].strip() if forwarded else request.META.get("REMOTE_ADDR")


def _enforce_activation_rate_limit(*, request):
    ip_address = _client_ip(request) or "unknown"
    digest = hashlib.sha256(ip_address.encode("utf-8")).hexdigest()
    key = f"devices:activation:{digest}"
    if cache.add(key, 1, settings.BM_DEVICE_ACTIVATION_RATE_LIMIT_WINDOW):
        return
    try:
        attempts = cache.incr(key)
    except ValueError:
        cache.set(key, 1, settings.BM_DEVICE_ACTIVATION_RATE_LIMIT_WINDOW)
        return
    if attempts > settings.BM_DEVICE_ACTIVATION_RATE_LIMIT_ATTEMPTS:
        raise DeviceActivationRateLimited()


def _read_refresh_cookie(request):
    value = request.COOKIES.get(settings.BM_DEVICE_REFRESH_COOKIE_NAME, "")
    credential_id, separator, raw_secret = value.partition(".")
    if not separator or not credential_id or not raw_secret:
        return None, None
    return credential_id, raw_secret


class DeviceListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        membership = require_company_permission(user=request.user, permission_code="devices.view")
        administrative_status = request.query_params.get("administrative_status", "").strip().upper()
        activation_status = request.query_params.get("activation_status", "").strip().upper()
        connectivity_status = request.query_params.get("connectivity_status", "").strip().upper()
        if administrative_status and administrative_status not in Device.AdministrativeStatus.values:
            raise ValidationError({"administrative_status": ["Estado administrativo no valido."]})
        if activation_status and activation_status not in Device.ActivationStatus.values:
            raise ValidationError({"activation_status": ["Estado de activacion no valido."]})
        if connectivity_status and connectivity_status not in Device.ConnectivityStatus.values:
            raise ValidationError({"connectivity_status": ["Estado de conectividad no valido."]})
        queryset = list_devices_for_membership(
            membership=membership,
            search=request.query_params.get("search", "").strip(),
            administrative_status=administrative_status,
            activation_status=activation_status,
            connectivity_status=connectivity_status,
            site_id=request.query_params.get("site_id"),
            zone_id=request.query_params.get("zone_id"),
        )
        response = _paginated_response(queryset=queryset, request=request, membership=membership)
        subscription = get_current_subscription_for_company(company=membership.company)
        limits = subscription.effective_limits() if subscription else {}
        response.data["permissions"] = {
            "can_create": membership_has_permission_on_any_scope(
                membership=membership,
                permission_code="devices.manage",
            )
        }
        response.data["usage"] = {
            "used": Device.objects.filter(company=membership.company)
            .exclude(administrative_status=Device.AdministrativeStatus.ARCHIVED)
            .count(),
            "limit": limits.get("devices"),
        }
        return response

    def post(self, request):
        membership = require_company_permission(user=request.user, permission_code="devices.manage")
        serializer = DeviceCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        device = create_device(company=membership.company, data=serializer.validated_data, actor=request.user)
        return Response(DeviceSerializer(device, context={"membership": membership}).data, status=status.HTTP_201_CREATED)


class DeviceDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, device_id):
        membership, device = _device_for_permission_or_raise(request=request, device_id=device_id, permission_code="devices.view")
        return Response(DeviceSerializer(device, context={"membership": membership}).data)

    def patch(self, request, device_id):
        membership, device = _device_for_permission_or_raise(request=request, device_id=device_id, permission_code="devices.manage")
        serializer = DeviceUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        device = update_device(device=device, data=serializer.validated_data)
        return Response(DeviceSerializer(device, context={"membership": membership}).data)


class DeviceZoneView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, device_id):
        membership, device = _device_for_permission_or_raise(request=request, device_id=device_id, permission_code="devices.manage")
        serializer = DeviceZoneUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        from apps.organizations.models import Zone

        zone = Zone.objects.select_related("site", "company").filter(id=serializer.validated_data["zone_id"]).first()
        if not zone:
            raise DeviceNotFound()
        require_company_permission(
            user=request.user,
            permission_code="devices.manage",
            scope=get_or_create_zone_scope(zone=zone),
        )
        device = change_device_zone(
            device=device,
            zone=zone,
            actor=request.user,
            expected_revision=serializer.validated_data["expected_revision"],
            reason=serializer.validated_data.get("reason", ""),
        )
        return Response(DeviceSerializer(device, context={"membership": membership}).data)


class DeviceStatusActionView(APIView):
    permission_classes = [IsAuthenticated]
    target_status = None

    def post(self, request, device_id):
        membership, device = _device_for_permission_or_raise(request=request, device_id=device_id, permission_code="devices.manage")
        serializer = DeviceExpectedRevisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        device = set_device_administrative_status(
            device=device,
            administrative_status=self.target_status,
            expected_revision=serializer.validated_data["expected_revision"],
        )
        return Response(DeviceSerializer(device, context={"membership": membership}).data)


class DeviceSuspendView(DeviceStatusActionView):
    target_status = Device.AdministrativeStatus.SUSPENDED


class DeviceReactivateView(DeviceStatusActionView):
    target_status = Device.AdministrativeStatus.ACTIVE


class DeviceArchiveView(DeviceStatusActionView):
    target_status = Device.AdministrativeStatus.ARCHIVED


class DeviceActivationCodeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, device_id):
        membership, device = _device_for_permission_or_raise(request=request, device_id=device_id, permission_code="devices.manage")
        activation, raw_code = generate_device_activation_code(device=device, created_by=request.user)
        return Response({"code": raw_code, "expires_at": activation.expires_at}, status=status.HTTP_201_CREATED)


class DeviceRevokeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, device_id):
        membership, device = _device_for_permission_or_raise(request=request, device_id=device_id, permission_code="devices.manage")
        serializer = DeviceExpectedRevisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        device = revoke_device(device=device, expected_revision=serializer.validated_data["expected_revision"])
        return Response(DeviceSerializer(device, context={"membership": membership}).data)


class DeviceCommandCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, device_id):
        membership, device = _device_for_permission_or_raise(
            request=request,
            device_id=device_id,
            permission_code="playback.view",
        )
        return _paginated_response(
            queryset=list_device_commands(device=device),
            request=request,
            membership=membership,
            serializer_class=DeviceCommandSerializer,
        )

    def post(self, request, device_id):
        serializer = DeviceCommandCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        permission_code = "playback.volume" if serializer.validated_data["command_type"] == "SET_VOLUME" else "playback.control"
        membership, device = _device_for_permission_or_raise(request=request, device_id=device_id, permission_code=permission_code)
        command = create_device_command(
            device=device,
            command_type=serializer.validated_data["command_type"],
            payload=serializer.validated_data.get("payload", {}),
            created_by=request.user,
            idempotency_key=serializer.validated_data.get("idempotency_key"),
        )
        return Response(DeviceCommandSerializer(command).data, status=status.HTTP_201_CREATED)


class DeviceEventListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, device_id):
        membership, device = _device_for_permission_or_raise(
            request=request,
            device_id=device_id,
            permission_code="playback.view",
        )
        return _paginated_response(
            queryset=list_device_events(device=device),
            request=request,
            membership=membership,
            serializer_class=DeviceEventSerializer,
        )


class PlayerActivationValidateView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        _enforce_activation_rate_limit(request=request)
        serializer = DeviceActivationValidateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        device = validate_device_activation_code(raw_code=serializer.validated_data["code"], ip_address=_client_ip(request))
        return Response(
            {
                "valid": True,
                "device": {"id": str(device.id), "code": device.code, "name": device.name},
                "zone": {"id": str(device.zone_id), "name": device.zone.name},
            }
        )


class PlayerActivationCompleteView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        _enforce_activation_rate_limit(request=request)
        serializer = DeviceActivationCompleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        device, credential, raw_secret = complete_device_activation(
            raw_code=serializer.validated_data["code"],
            ip_address=_client_ip(request),
            device_name=serializer.validated_data.get("device_name", ""),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
            app_version=serializer.validated_data.get("app_version", ""),
        )
        access, expires_in = issue_device_access_token(device=device, credential=credential)
        response = Response(
            {
                "device_access": access,
                "expires_in": expires_in,
                "device": {"id": str(device.id), "code": device.code, "name": device.name},
                "zone": {"id": str(device.zone_id), "name": device.zone.name},
                "next_step": "PLAYER",
            }
        )
        set_device_refresh_cookie(response, credential_id=credential.credential_id, raw_secret=raw_secret)
        return response


class PlayerTokenRefreshView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        credential_id, raw_secret = _read_refresh_cookie(request)
        if not credential_id:
            from apps.devices.exceptions import DeviceSessionExpired

            raise DeviceSessionExpired()
        device, credential, next_raw_secret = rotate_device_credential(credential_id=credential_id, raw_secret=raw_secret)
        access, expires_in = issue_device_access_token(device=device, credential=credential)
        response = Response(
            {
                "device_access": access,
                "expires_in": expires_in,
                "device": {"id": str(device.id), "code": device.code, "name": device.name},
                "zone": {"id": str(device.zone_id), "name": device.zone.name},
            }
        )
        set_device_refresh_cookie(response, credential_id=credential.credential_id, raw_secret=next_raw_secret)
        return response


class PlayerLogoutView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        credential_id, raw_secret = _read_refresh_cookie(request)
        if credential_id:
            revoke_device_credential_from_cookie(credential_id=credential_id, raw_secret=raw_secret)
        response = Response(status=status.HTTP_204_NO_CONTENT)
        clear_device_refresh_cookie(response)
        return response


class PlayerSessionView(APIView):
    authentication_classes = [DeviceJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        device = request.user.device
        return Response(
            {
                "device": {"id": str(device.id), "code": device.code, "name": device.name},
                "zone": {"id": str(device.zone_id), "name": device.zone.name},
            }
        )


class InternalDeviceTokenIntrospectionView(APIView):
    authentication_classes = []
    permission_classes = [HasGoServiceToken]

    def post(self, request):
        token = request.data.get("token", "")
        if not isinstance(token, str) or not token:
            raise ValidationError({"token": ["Este campo es obligatorio."]})
        principal, payload = authenticate_device_access_token(token=token)
        device = principal.device
        return Response(
            {
                "active": True,
                "device_id": str(device.id),
                "company_id": str(device.company_id),
                "zone_id": str(device.zone_id),
                "credential_id": principal.credential.credential_id,
                "expires_at": payload["exp"],
            }
        )
