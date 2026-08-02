from rest_framework.permissions import BasePermission

from apps.users.selectors import build_user_session_context, get_active_company_membership, user_has_active_platform_role


class IsInternalPlatformUser(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and user_has_active_platform_role(user=request.user))


class IsVerifiedClient(BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.email_verified_at
            and not user_has_active_platform_role(user=request.user)
        )


class HasActiveCompanyMembership(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and get_active_company_membership(user=request.user))


class HasFunctionalSubscriptionAccess(BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        context = build_user_session_context(user=request.user)
        return bool(context["functional_access"])
