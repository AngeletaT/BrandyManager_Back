from django.utils import timezone

from apps.organizations.models import MembershipPermissionOverride


def resolve_effective_permissions(*, membership, scope, at=None):
    at = at or timezone.now()
    permission_codes = set()

    grants = (
        membership.grants.filter(is_active=True, scope=scope)
        .select_related("role")
        .prefetch_related("role__role_permissions__permission")
    )
    for grant in grants:
        if grant.starts_at and grant.starts_at > at:
            continue
        if grant.ends_at and grant.ends_at <= at:
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
