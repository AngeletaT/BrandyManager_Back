from django.utils import timezone
from rest_framework import status

from apps.billing.selectors import get_current_subscription_for_company
from apps.organizations.models import CompanyMembership, MembershipGrant, MembershipPermissionOverride, ResourceScope, Zone
from apps.users.selectors import user_has_active_platform_role
from shared.api.exceptions import DomainError


class CompanyAccessDenied(DomainError):
    def __init__(self):
        super().__init__(
            code="company_access_denied",
            message="No tienes acceso a esta empresa.",
            status_code=status.HTTP_403_FORBIDDEN,
        )


class ResourceScopeDenied(DomainError):
    def __init__(self):
        super().__init__(
            code="resource_scope_denied",
            message="No tienes acceso a este recurso.",
            status_code=status.HTTP_403_FORBIDDEN,
        )


class PermissionDenied(DomainError):
    def __init__(self):
        super().__init__(
            code="permission_denied",
            message="No tienes permiso para realizar esta accion.",
            status_code=status.HTTP_403_FORBIDDEN,
        )


class FunctionalAccessBlocked(DomainError):
    def __init__(self, *, reason="functional_access_blocked"):
        super().__init__(
            code="functional_access_blocked",
            message="La cuenta no tiene acceso funcional al producto.",
            status_code=status.HTTP_403_FORBIDDEN,
            extra={"block_reason": reason},
        )


def _grant_is_current(*, grant, at):
    return (
        grant.is_active
        and (grant.starts_at is None or grant.starts_at <= at)
        and (grant.ends_at is None or grant.ends_at > at)
    )


def _scope_matches(*, grant_scope, target_scope):
    if grant_scope.company_id != target_scope.company_id:
        return False
    if grant_scope.scope_type == ResourceScope.ScopeType.COMPANY:
        return True
    if target_scope.scope_type == ResourceScope.ScopeType.COMPANY:
        return False
    if grant_scope.scope_type == ResourceScope.ScopeType.SITE:
        if target_scope.scope_type == ResourceScope.ScopeType.SITE:
            return grant_scope.site_id == target_scope.site_id
        if target_scope.scope_type == ResourceScope.ScopeType.ZONE:
            return target_scope.zone.site_id == grant_scope.site_id
    if grant_scope.scope_type == ResourceScope.ScopeType.ZONE:
        return target_scope.scope_type == ResourceScope.ScopeType.ZONE and grant_scope.zone_id == target_scope.zone_id
    return grant_scope.id == target_scope.id


def resolve_effective_permissions(*, membership, scope, at=None):
    at = at or timezone.now()
    permission_codes = set()

    grants = (
        membership.grants.filter(is_active=True)
        .select_related("role", "scope", "scope__site", "scope__zone")
        .prefetch_related("role__role_permissions__permission")
    )
    for grant in grants:
        if not _grant_is_current(grant=grant, at=at):
            continue
        if not _scope_matches(grant_scope=grant.scope, target_scope=scope):
            continue
        for role_permission in grant.role.role_permissions.all():
            permission_codes.add(role_permission.permission.code)

    overrides = (
        MembershipPermissionOverride.objects.filter(membership=membership, scope=scope)
        .select_related("permission")
        .order_by("created_at")
    )
    for override in overrides:
        if override.starts_at and override.starts_at > at:
            continue
        if override.ends_at and override.ends_at <= at:
            continue
        if override.effect == MembershipPermissionOverride.Effect.ALLOW:
            permission_codes.add(override.permission.code)
        if override.effect == MembershipPermissionOverride.Effect.DENY:
            permission_codes.discard(override.permission.code)

    return permission_codes


def membership_has_permission(*, membership, permission_code, scope, at=None):
    return permission_code in resolve_effective_permissions(membership=membership, scope=scope, at=at)


def membership_has_permission_on_any_scope(*, membership, permission_code, at=None):
    at = at or timezone.now()
    grants = (
        membership.grants.filter(is_active=True)
        .select_related("role")
        .prefetch_related("role__role_permissions__permission")
    )
    for grant in grants:
        if not _grant_is_current(grant=grant, at=at):
            continue
        if any(role_permission.permission.code == permission_code for role_permission in grant.role.role_permissions.all()):
            return True
    return False


def get_active_client_membership_or_raise(*, user):
    if not user or not user.is_authenticated or user_has_active_platform_role(user=user):
        raise CompanyAccessDenied()
    if not user.is_active:
        raise CompanyAccessDenied()
    if not user.email_verified_at:
        raise CompanyAccessDenied()
    membership = (
        CompanyMembership.objects.select_related("company", "user")
        .filter(user=user, status=CompanyMembership.Status.ACTIVE)
        .first()
    )
    if not membership:
        raise CompanyAccessDenied()
    return membership


def ensure_functional_access(*, membership, at=None):
    subscription = get_current_subscription_for_company(company=membership.company)
    if not subscription:
        raise FunctionalAccessBlocked(reason="subscription_required")
    if not subscription.has_functional_access(at=at):
        raise FunctionalAccessBlocked(reason=subscription.access_block_reason(at=at))
    return subscription


def require_company_permission(*, user, permission_code, scope=None, at=None, check_functional_access=True):
    membership = get_active_client_membership_or_raise(user=user)
    if check_functional_access:
        ensure_functional_access(membership=membership, at=at)
    target_scope = scope or get_company_scope(company=membership.company)
    if target_scope.company_id != membership.company_id:
        raise CompanyAccessDenied()
    if target_scope.scope_type == ResourceScope.ScopeType.COMPANY:
        if membership_has_permission_on_any_scope(membership=membership, permission_code=permission_code, at=at):
            return membership
    if not membership_has_permission(membership=membership, permission_code=permission_code, scope=target_scope, at=at):
        raise PermissionDenied()
    return membership


def get_company_scope(*, company):
    return ResourceScope.objects.get_or_create(
        company=company,
        scope_type=ResourceScope.ScopeType.COMPANY,
        defaults={"name": f"{company.trade_name} - Empresa", "is_system_generated": True},
    )[0]


def get_or_create_site_scope(*, site):
    return ResourceScope.objects.get_or_create(
        company=site.company,
        scope_type=ResourceScope.ScopeType.SITE,
        site=site,
        defaults={"name": f"{site.name} - Sede", "is_system_generated": True},
    )[0]


def get_or_create_zone_scope(*, zone):
    return ResourceScope.objects.get_or_create(
        company=zone.company,
        scope_type=ResourceScope.ScopeType.ZONE,
        zone=zone,
        defaults={"name": f"{zone.name} - Zona", "is_system_generated": True},
    )[0]


def site_ids_accessible_by_membership(*, membership, permission_code, at=None):
    at = at or timezone.now()
    company_scope = get_company_scope(company=membership.company)
    if membership_has_permission(membership=membership, permission_code=permission_code, scope=company_scope, at=at):
        return None
    ids = set()
    grants = MembershipGrant.objects.filter(membership=membership, is_active=True).select_related("scope", "scope__site", "scope__zone")
    for grant in grants:
        if not _grant_is_current(grant=grant, at=at):
            continue
        if permission_code not in resolve_effective_permissions(membership=membership, scope=grant.scope, at=at):
            continue
        if grant.scope.scope_type == ResourceScope.ScopeType.SITE and grant.scope.site_id:
            ids.add(grant.scope.site_id)
        if grant.scope.scope_type == ResourceScope.ScopeType.ZONE and grant.scope.zone_id:
            ids.add(grant.scope.zone.site_id)
    return ids


def zone_ids_accessible_by_membership(*, membership, permission_code, at=None):
    at = at or timezone.now()
    company_scope = get_company_scope(company=membership.company)
    if membership_has_permission(membership=membership, permission_code=permission_code, scope=company_scope, at=at):
        return None
    zone_ids = set()
    site_ids = set()
    grants = MembershipGrant.objects.filter(membership=membership, is_active=True).select_related("scope", "scope__site", "scope__zone")
    for grant in grants:
        if not _grant_is_current(grant=grant, at=at):
            continue
        if permission_code not in resolve_effective_permissions(membership=membership, scope=grant.scope, at=at):
            continue
        if grant.scope.scope_type == ResourceScope.ScopeType.SITE and grant.scope.site_id:
            site_ids.add(grant.scope.site_id)
        if grant.scope.scope_type == ResourceScope.ScopeType.ZONE and grant.scope.zone_id:
            zone_ids.add(grant.scope.zone_id)
    if site_ids:
        zone_ids.update(Zone.objects.filter(site_id__in=site_ids).values_list("id", flat=True))
    return zone_ids
