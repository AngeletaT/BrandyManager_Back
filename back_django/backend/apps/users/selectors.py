from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone

from apps.billing.selectors import get_current_subscription_for_company
from apps.organizations.models import CompanyMembership, MembershipGrant
from apps.users.models import UserActionToken


User = get_user_model()


def get_user_by_email(*, email):
    return User.objects.filter(email__iexact=email).first()


def user_exists_by_email(*, email):
    return User.objects.filter(email__iexact=email).exists()


def user_has_active_platform_role(*, user):
    return user.platform_roles.filter(revoked_at__isnull=True, role__is_active=True).exists()


def user_has_active_company_membership(*, user):
    return user.company_memberships.filter(status="ACTIVE").exists()


def get_user_account_classification(*, user):
    if user_has_active_platform_role(user=user):
        return "internal"
    if user_has_active_company_membership(user=user):
        return "client_active"
    return "client_pending"


def get_latest_action_token(*, user, purpose):
    return UserActionToken.objects.filter(user=user, purpose=purpose).order_by("-created_at").first()


def get_active_platform_role_assignment(*, user):
    return user.platform_roles.select_related("role").filter(revoked_at__isnull=True, role__is_active=True).first()


def get_active_company_membership(*, user):
    return (
        CompanyMembership.objects.select_related("company", "user")
        .filter(user=user, status=CompanyMembership.Status.ACTIVE)
        .first()
    )


def get_active_company_role_for_membership(*, membership, at=None):
    at = at or timezone.now()
    grant = (
        MembershipGrant.objects.select_related("role")
        .filter(
            membership=membership,
            is_active=True,
        )
        .filter(
            Q(starts_at__isnull=True) | Q(starts_at__lte=at),
            Q(ends_at__isnull=True) | Q(ends_at__gt=at),
        )
        .order_by("-created_at")
        .first()
    )
    return grant.role if grant else None


def build_user_session_context(*, user, at=None):
    at = at or timezone.now()
    if get_active_platform_role_assignment(user=user):
        return {
            "access_type": "internal_admin",
            "onboarding_required": False,
            "company": None,
            "membership": None,
            "company_role": None,
            "subscription": None,
            "functional_access": True,
            "block_reason": None,
            "next_step": "ADMIN",
        }

    membership = get_active_company_membership(user=user)
    if not membership:
        return {
            "access_type": "client_pending",
            "onboarding_required": True,
            "company": None,
            "membership": None,
            "company_role": None,
            "subscription": None,
            "functional_access": False,
            "block_reason": "onboarding_required",
            "next_step": "ONBOARDING",
        }

    company = membership.company
    company_role = get_active_company_role_for_membership(membership=membership, at=at)
    subscription = get_current_subscription_for_company(company=company)
    subscription_context = None
    functional_access = False
    block_reason = "subscription_required"
    if subscription:
        functional_access = subscription.has_functional_access(at=at)
        block_reason = subscription.access_block_reason(at=at) or None
        subscription_context = {
            "id": str(subscription.id),
            "plan_code": subscription.plan.code if subscription.plan_id else subscription.plan_snapshot.get("code"),
            "status": subscription.status,
            "trial_ends_at": subscription.trial_ends_at,
            "effective_limits": subscription.effective_limits(),
            "functional_access": functional_access,
            "block_reason": block_reason,
        }

    return {
        "access_type": "client",
        "onboarding_required": False,
        "company": {
            "id": str(company.id),
            "legal_name": company.legal_name,
            "trade_name": company.trade_name,
            "status": company.status,
        },
        "membership": {
            "id": str(membership.id),
            "status": membership.status,
        },
        "company_role": {
            "code": company_role.code,
            "name": company_role.name,
        }
        if company_role
        else None,
        "subscription": subscription_context,
        "functional_access": functional_access,
        "block_reason": block_reason,
        "next_step": "APP" if functional_access else "BILLING",
    }


def build_user_session_payload(*, user, access, at=None):
    return {
        "access": access,
        "user": {
            "id": str(user.id),
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email_verified": bool(user.email_verified_at),
        },
        "context": build_user_session_context(user=user, at=at),
    }
