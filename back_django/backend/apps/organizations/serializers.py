from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils import timezone
from rest_framework import serializers

from apps.authorization.services import get_company_scope, get_or_create_site_scope, get_or_create_zone_scope, membership_has_permission
from apps.billing.selectors import get_current_subscription_for_company
from apps.organizations.models import Company, CompanyInvitation, CompanyMembership, MembershipGrant, ResourceScope, Site, Zone
from apps.organizations.normalization import normalize_country_code, normalize_tax_id


class CompanyDetailSerializer(serializers.ModelSerializer):
    sector = serializers.SerializerMethodField()
    estimated_sites = serializers.SerializerMethodField()
    permissions = serializers.SerializerMethodField()
    usage = serializers.SerializerMethodField()

    class Meta:
        model = Company
        fields = [
            "id",
            "legal_name",
            "trade_name",
            "tax_id",
            "billing_email",
            "contact_email",
            "phone",
            "country_code",
            "default_timezone",
            "default_language",
            "status",
            "settings",
            "sector",
            "estimated_sites",
            "created_at",
            "updated_at",
            "permissions",
            "usage",
        ]
        read_only_fields = ["id", "status", "settings", "created_at", "updated_at", "permissions", "usage"]

    def get_sector(self, obj):
        return (obj.settings or {}).get("onboarding", {}).get("sector", "")

    def get_estimated_sites(self, obj):
        return (obj.settings or {}).get("onboarding", {}).get("estimated_sites", "")

    def get_permissions(self, obj):
        membership = self.context.get("membership")
        if not membership:
            return {"can_update": False}
        return {
            "can_update": membership_has_permission(
                membership=membership,
                permission_code="company.update",
                scope=get_company_scope(company=obj),
            )
        }

    def get_usage(self, obj):
        subscription = get_current_subscription_for_company(company=obj)
        limits = subscription.effective_limits() if subscription else {}
        return {
            "sites": {
                "used": Site.objects.filter(company=obj).exclude(status=Site.Status.ARCHIVED).count(),
                "limit": limits.get("sites"),
            },
            "zones": {
                "used": Zone.objects.filter(company=obj).exclude(status=Zone.Status.ARCHIVED).count(),
                "limit": limits.get("zones"),
            },
            "users": {
                "used": CompanyMembership.objects.filter(company=obj).exclude(status=CompanyMembership.Status.REVOKED).count()
                + CompanyInvitation.objects.filter(
                    company=obj,
                    accepted_at__isnull=True,
                    cancelled_at__isnull=True,
                    expires_at__gt=timezone.now(),
                ).count(),
                "limit": limits.get("users"),
            },
        }


class CompanyUpdateSerializer(serializers.Serializer):
    FORBIDDEN_FIELDS = {
        "id",
        "status",
        "subscription",
        "plan",
        "roles",
        "role",
        "company_role",
        "memberships",
        "settings",
        "is_staff",
        "is_superuser",
        "platform_role",
        "platform_roles",
        "PlatformRole",
    }

    legal_name = serializers.CharField(max_length=255, required=False)
    trade_name = serializers.CharField(max_length=255, required=False)
    tax_id = serializers.CharField(max_length=64, required=False)
    billing_email = serializers.EmailField(required=False)
    contact_email = serializers.EmailField(required=False)
    phone = serializers.CharField(max_length=50, required=False, allow_blank=True)
    country_code = serializers.CharField(max_length=2, required=False)
    default_timezone = serializers.CharField(max_length=64, required=False)
    default_language = serializers.CharField(max_length=10, required=False)
    sector = serializers.CharField(max_length=80, required=False, allow_blank=True)

    def validate(self, attrs):
        forbidden = sorted(set(self.initial_data) & self.FORBIDDEN_FIELDS)
        if forbidden:
            raise serializers.ValidationError(
                {field: ["Este campo no puede actualizarse desde este endpoint."] for field in forbidden}
            )
        for field, value in list(attrs.items()):
            if isinstance(value, str):
                attrs[field] = value.strip()
        if "tax_id" in attrs:
            attrs["tax_id"] = normalize_tax_id(attrs["tax_id"])
        if "country_code" in attrs:
            attrs["country_code"] = normalize_country_code(attrs["country_code"])
        if "default_language" in attrs:
            attrs["default_language"] = attrs["default_language"].strip().lower()
        if "default_timezone" in attrs:
            try:
                ZoneInfo(attrs["default_timezone"])
            except ZoneInfoNotFoundError as exc:
                raise serializers.ValidationError({"default_timezone": ["Zona horaria no valida."]}) from exc
        return attrs


class SiteSerializer(serializers.ModelSerializer):
    zone_count = serializers.SerializerMethodField()
    permissions = serializers.SerializerMethodField()

    class Meta:
        model = Site
        fields = [
            "id",
            "name",
            "code",
            "site_type",
            "description",
            "status",
            "address_line_1",
            "address_line_2",
            "postal_code",
            "city",
            "province",
            "country_code",
            "timezone",
            "contact_name",
            "contact_email",
            "contact_phone",
            "zone_count",
            "archived_at",
            "created_at",
            "updated_at",
            "permissions",
        ]
        read_only_fields = ["id", "status", "zone_count", "archived_at", "created_at", "updated_at", "permissions"]

    def get_zone_count(self, obj):
        return obj.zones.exclude(status=Zone.Status.ARCHIVED).count()

    def get_permissions(self, obj):
        membership = self.context.get("membership")
        if not membership:
            return {"can_view": True, "can_update": False, "can_archive": False}
        scope = get_or_create_site_scope(site=obj)
        is_archived = obj.status == Site.Status.ARCHIVED
        can_update = (
            not is_archived
            and (
                membership_has_permission(membership=membership, permission_code="sites.update", scope=scope)
                or membership_has_permission(membership=membership, permission_code="sites.update_operational", scope=scope)
            )
        )
        return {
            "can_view": True,
            "can_update": can_update,
            "can_archive": (not is_archived)
            and membership_has_permission(membership=membership, permission_code="sites.archive", scope=scope),
        }


class SiteCreateSerializer(serializers.Serializer):
    FORBIDDEN_FIELDS = {"company", "company_id", "status", "archived_at"}

    name = serializers.CharField(max_length=255)
    code = serializers.CharField(max_length=64, required=False, allow_blank=True)
    site_type = serializers.ChoiceField(choices=Site.SiteType.choices, default=Site.SiteType.BRANCH)
    description = serializers.CharField(required=False, allow_blank=True)
    address_line_1 = serializers.CharField(max_length=255)
    address_line_2 = serializers.CharField(max_length=255, required=False, allow_blank=True)
    postal_code = serializers.CharField(max_length=20, required=False, allow_blank=True)
    city = serializers.CharField(max_length=120)
    province = serializers.CharField(max_length=120, required=False, allow_blank=True)
    country_code = serializers.CharField(max_length=2, required=False, allow_blank=True)
    timezone = serializers.CharField(max_length=64, required=False, allow_blank=True)
    contact_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    contact_email = serializers.EmailField(required=False, allow_blank=True)
    contact_phone = serializers.CharField(max_length=50, required=False, allow_blank=True)
    def validate(self, attrs):
        forbidden = sorted(set(self.initial_data) & self.FORBIDDEN_FIELDS)
        if forbidden:
            raise serializers.ValidationError(
                {field: ["Este campo no puede enviarse desde este endpoint."] for field in forbidden}
            )
        for field, value in list(attrs.items()):
            if isinstance(value, str):
                attrs[field] = value.strip()
        if "code" in attrs and attrs["code"]:
            attrs["code"] = attrs["code"].upper()
        if "country_code" in attrs and attrs["country_code"]:
            attrs["country_code"] = normalize_country_code(attrs["country_code"])
        if "timezone" in attrs and attrs["timezone"]:
            try:
                ZoneInfo(attrs["timezone"])
            except ZoneInfoNotFoundError as exc:
                raise serializers.ValidationError({"timezone": ["Zona horaria no valida."]}) from exc
        return attrs


class SiteUpdateSerializer(SiteCreateSerializer):
    name = serializers.CharField(max_length=255, required=False)
    address_line_1 = serializers.CharField(max_length=255, required=False)
    city = serializers.CharField(max_length=120, required=False)


class ZoneSerializer(serializers.ModelSerializer):
    site = serializers.SerializerMethodField()
    permissions = serializers.SerializerMethodField()
    channel = serializers.SerializerMethodField()
    device_count = serializers.SerializerMethodField()

    class Meta:
        model = Zone
        fields = [
            "id",
            "site",
            "name",
            "code",
            "description",
            "status",
            "timezone",
            "channel",
            "device_count",
            "created_at",
            "updated_at",
            "permissions",
        ]
        read_only_fields = ["id", "site", "status", "created_at", "updated_at", "permissions"]

    def get_site(self, obj):
        return {"id": str(obj.site_id), "name": obj.site.name}

    def get_channel(self, obj):
        assignments = getattr(obj, "active_channel_assignments", [])
        if not assignments:
            return None
        channel = assignments[0].channel
        return {"id": str(channel.id), "name": channel.name, "status": channel.status}

    def get_device_count(self, obj):
        return getattr(obj, "active_device_count", 0)

    def get_permissions(self, obj):
        membership = self.context.get("membership")
        if not membership:
            return {"can_view": True, "can_update": False, "can_archive": False}
        scope = get_or_create_zone_scope(zone=obj)
        is_archived = obj.status == Zone.Status.ARCHIVED or obj.site.status == Site.Status.ARCHIVED
        can_update = (
            not is_archived
            and (
                membership_has_permission(membership=membership, permission_code="zones.update", scope=scope)
                or membership_has_permission(membership=membership, permission_code="zones.update_operational", scope=scope)
            )
        )
        return {
            "can_view": True,
            "can_update": can_update,
            "can_archive": (not is_archived)
            and membership_has_permission(membership=membership, permission_code="zones.archive", scope=scope),
        }


class ZoneCreateSerializer(serializers.Serializer):
    FORBIDDEN_FIELDS = {
        "company",
        "company_id",
        "site",
        "status",
        "archived_at",
        "metadata",
        "channel_id",
        "device_id",
        "schedule_id",
    }

    site_id = serializers.UUIDField()
    name = serializers.CharField(max_length=255)
    code = serializers.CharField(max_length=64, required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)
    timezone = serializers.CharField(max_length=64, required=False, allow_blank=True)

    def validate(self, attrs):
        forbidden = sorted(set(self.initial_data) & self.FORBIDDEN_FIELDS)
        if forbidden:
            raise serializers.ValidationError(
                {field: ["Este campo no puede enviarse desde este endpoint."] for field in forbidden}
            )
        for field, value in list(attrs.items()):
            if isinstance(value, str):
                attrs[field] = value.strip()
        if "code" in attrs and attrs["code"]:
            attrs["code"] = attrs["code"].upper()
        if "timezone" in attrs:
            if attrs["timezone"]:
                try:
                    ZoneInfo(attrs["timezone"])
                except ZoneInfoNotFoundError as exc:
                    raise serializers.ValidationError({"timezone": ["Zona horaria no valida."]}) from exc
            else:
                attrs["timezone"] = None
        return attrs


class ZoneUpdateSerializer(ZoneCreateSerializer):
    FORBIDDEN_FIELDS = ZoneCreateSerializer.FORBIDDEN_FIELDS | {"site_id"}

    site_id = None
    name = serializers.CharField(max_length=255, required=False)
    code = serializers.CharField(max_length=64, required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)
    timezone = serializers.CharField(max_length=64, required=False, allow_blank=True)


class ScopeSummarySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    scope_type = serializers.CharField()
    site_id = serializers.UUIDField(allow_null=True)
    zone_id = serializers.UUIDField(allow_null=True)
    name = serializers.CharField()


def serialize_membership(membership, *, actor_membership=None):
    active_grants = [
        grant
        for grant in membership.grants.all()
        if grant.is_active and grant.ends_at is None
    ]
    role = active_grants[0].role if active_grants else None
    scopes = []
    for grant in active_grants:
        scope = grant.scope
        scopes.append(
            {
                "type": scope.scope_type,
                "id": str(scope.id),
                "name": scope.name,
                "site_id": str(scope.site_id) if scope.site_id else None,
                "zone_id": str(scope.zone_id) if scope.zone_id else None,
            }
        )
    is_owner = role and role.code == "OWNER"
    company_scope = get_company_scope(company=membership.company)
    can_update_role = bool(
        actor_membership
        and not is_owner
        and membership_has_permission(membership=actor_membership, permission_code="users.update_role", scope=company_scope)
    )
    can_suspend = bool(
        actor_membership
        and not is_owner
        and membership.status == CompanyMembership.Status.ACTIVE
        and membership_has_permission(membership=actor_membership, permission_code="users.suspend", scope=company_scope)
    )
    can_reactivate = bool(
        actor_membership
        and not is_owner
        and membership.status == CompanyMembership.Status.SUSPENDED
        and membership_has_permission(membership=actor_membership, permission_code="users.reactivate", scope=company_scope)
    )
    return {
        "id": str(membership.id),
        "status": membership.status,
        "user": {
            "id": str(membership.user.id),
            "email": membership.user.email,
            "first_name": membership.user.first_name,
            "last_name": membership.user.last_name,
            "email_verified": bool(membership.user.email_verified_at),
            "is_active": membership.user.is_active,
        },
        "company_role": {"code": role.code, "name": role.name} if role else None,
        "scopes": scopes,
        "joined_at": membership.accepted_at or membership.created_at,
        "invited_at": membership.invited_at,
        "accepted_at": membership.accepted_at,
        "last_access_at": membership.last_access_at,
        "created_at": membership.created_at,
        "updated_at": membership.updated_at,
        "permissions": {
            "can_update_role": can_update_role,
            "can_suspend": can_suspend,
            "can_reactivate": can_reactivate,
        },
    }


def _serialize_scope(scope):
    return {
        "type": scope.scope_type,
        "id": str(scope.id),
        "name": scope.name,
        "site_id": str(scope.site_id) if scope.site_id else None,
        "zone_id": str(scope.zone_id) if scope.zone_id else None,
    }


def serialize_invitation(invitation, *, scopes=None, actor_membership=None):
    now = timezone.now()
    if invitation.accepted_at:
        status_value = "ACCEPTED"
    elif invitation.cancelled_at:
        status_value = "CANCELLED"
    elif invitation.expires_at <= now:
        status_value = "EXPIRED"
    else:
        status_value = "PENDING"
    invited_name = " ".join(part for part in [invitation.first_name, invitation.last_name] if part).strip()
    can_manage = status_value == "PENDING"
    return {
        "id": str(invitation.id),
        "status": status_value,
        "invited_email": invitation.invited_email,
        "invited_name": invited_name,
        "role": {"code": invitation.role.code, "name": invitation.role.name},
        "scopes": [_serialize_scope(scope) for scope in (scopes or [])],
        "expires_at": invitation.expires_at,
        "created_at": invitation.created_at,
        "invited_by": {
            "id": str(invitation.invited_by_id),
            "email": invitation.invited_by.email,
        }
        if invitation.invited_by_id
        else None,
        "actions": {
            "can_resend": can_manage,
            "can_cancel": can_manage,
        },
    }


class InvitationCreateSerializer(serializers.Serializer):
    email = serializers.EmailField()
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    role_code = serializers.ChoiceField(choices=["MANAGER", "EDITOR_PLAYLISTS", "OPERADOR_SEDES", "VIEWER"])
    site_ids = serializers.ListField(child=serializers.UUIDField(), required=False, allow_empty=True)
    zone_ids = serializers.ListField(child=serializers.UUIDField(), required=False, allow_empty=True)

    def validate(self, attrs):
        for field, value in list(attrs.items()):
            if isinstance(value, str):
                attrs[field] = value.strip()
        return attrs


class MembershipUpdateSerializer(serializers.Serializer):
    role_code = serializers.ChoiceField(choices=["MANAGER", "EDITOR_PLAYLISTS", "OPERADOR_SEDES", "VIEWER"])
    site_ids = serializers.ListField(child=serializers.UUIDField(), required=False, allow_empty=True)
    zone_ids = serializers.ListField(child=serializers.UUIDField(), required=False, allow_empty=True)


class InvitationValidateSerializer(serializers.Serializer):
    token = serializers.CharField()


class InvitationAcceptSerializer(serializers.Serializer):
    token = serializers.CharField()
    password = serializers.CharField(required=False, allow_blank=False, write_only=True)
    password_confirmation = serializers.CharField(required=False, allow_blank=False, write_only=True)

    def validate(self, attrs):
        password = attrs.get("password")
        confirmation = attrs.get("password_confirmation")
        if password or confirmation:
            if password != confirmation:
                raise serializers.ValidationError({"password_confirmation": ["Las contrasenas no coinciden."]})
        return attrs
