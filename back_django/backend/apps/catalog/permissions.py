from rest_framework.permissions import BasePermission

from apps.authorization.models import UserPlatformRole


def user_has_platform_permission(*, user, permission_code):
    if not user or not user.is_authenticated or not user.is_active:
        return False
    return UserPlatformRole.objects.filter(
        user=user,
        revoked_at__isnull=True,
        role__is_active=True,
        role__role_permissions__permission__code=permission_code,
        role__role_permissions__permission__is_active=True,
    ).exists()


class CanManageInternalCatalog(BasePermission):
    def has_permission(self, request, view):
        return user_has_platform_permission(user=request.user, permission_code="platform.content.manage")
