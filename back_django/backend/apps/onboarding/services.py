from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.authorization.catalog import OWNER_COMPANY_ROLE_CODE
from apps.authorization.models import CompanyRole
from apps.billing.models import Plan
from apps.billing.plans import TRIAL_PLAN_CODE
from apps.billing.services import create_trial_subscription
from apps.organizations.models import Company, CompanyMembership, MembershipGrant, ResourceScope
from apps.users.exceptions import EmailNotVerified, UserInactive
from apps.users.selectors import user_has_active_platform_role

from apps.onboarding.exceptions import (
    CompanyTaxIdAlreadyRegistered,
    OnboardingAlreadyCompleted,
    OnboardingConfigurationMissing,
    OnboardingNotAllowed,
)


UserModel = get_user_model()


def _raise_known_integrity_error(exc):
    message = str(exc)
    if "uniq_company_tax_id" in message:
        raise CompanyTaxIdAlreadyRegistered() from exc
    if "uniq_company_membership_single_company_per_user" in message:
        raise OnboardingAlreadyCompleted() from exc
    raise exc


def _get_owner_role_for_update():
    try:
        return CompanyRole.objects.select_for_update().get(
            company=None,
            code=OWNER_COMPANY_ROLE_CODE,
            is_active=True,
        )
    except CompanyRole.DoesNotExist as exc:
        raise OnboardingConfigurationMissing() from exc


def _ensure_trial_plan_exists_for_update():
    try:
        Plan.objects.select_for_update().get(code=TRIAL_PLAN_CODE, is_active=True)
    except Plan.DoesNotExist as exc:
        raise OnboardingConfigurationMissing() from exc


def _build_onboarding_settings(*, sector, estimated_sites, user, completed_at):
    return {
        "onboarding": {
            "sector": sector,
            "estimated_sites": estimated_sites,
            "completed_by_user_id": str(user.id),
            "completed_at": completed_at.isoformat(),
        }
    }


def serialize_onboarding_result(*, company, membership, role, subscription):
    return {
        "company": {
            "id": str(company.id),
            "legal_name": company.legal_name,
            "trade_name": company.trade_name,
            "tax_id": company.tax_id,
            "status": company.status,
        },
        "membership": {
            "id": str(membership.id),
            "status": membership.status,
        },
        "company_role": {
            "code": role.code,
            "name": role.name,
        },
        "subscription": {
            "id": str(subscription.id),
            "plan_code": subscription.plan.code if subscription.plan_id else TRIAL_PLAN_CODE,
            "status": subscription.status,
            "trial_started_at": subscription.trial_started_at,
            "trial_ends_at": subscription.trial_ends_at,
            "effective_limits": subscription.effective_limits(),
            "functional_access": subscription.has_functional_access(),
            "block_reason": subscription.access_block_reason() or None,
        },
        "next_step": "APP",
    }


def complete_client_onboarding(*, user, data):
    try:
        with transaction.atomic():
            now = timezone.now()
            locked_user = UserModel.objects.select_for_update().get(pk=user.pk)

            if not locked_user.is_active:
                raise UserInactive()
            if not locked_user.email_verified_at:
                raise EmailNotVerified()
            if locked_user.is_staff or locked_user.is_superuser or user_has_active_platform_role(user=locked_user):
                raise OnboardingNotAllowed()

            existing_memberships = CompanyMembership.objects.select_for_update().filter(user=locked_user)
            if existing_memberships.exists():
                raise OnboardingAlreadyCompleted()

            if Company.objects.select_for_update().filter(tax_id=data["tax_id"]).exists():
                raise CompanyTaxIdAlreadyRegistered()

            owner_role = _get_owner_role_for_update()
            _ensure_trial_plan_exists_for_update()

            company = Company(
                legal_name=data["legal_name"],
                trade_name=data["trade_name"],
                tax_id=data["tax_id"],
                billing_email=data["billing_email"],
                contact_email=data["contact_email"],
                phone=data.get("phone", ""),
                country_code=data["country_code"],
                default_timezone=data["default_timezone"],
                default_language=data["default_language"],
                status=Company.Status.TRIAL,
                settings=_build_onboarding_settings(
                    sector=data["sector"],
                    estimated_sites=data["estimated_sites"],
                    user=locked_user,
                    completed_at=now,
                ),
            )
            company.full_clean()
            company.save()

            membership = CompanyMembership(
                company=company,
                user=locked_user,
                status=CompanyMembership.Status.ACTIVE,
                accepted_at=now,
                last_access_at=now,
            )
            membership.full_clean()
            membership.save()

            scope = ResourceScope(
                company=company,
                scope_type=ResourceScope.ScopeType.COMPANY,
                name=f"{company.trade_name} - Empresa",
                is_system_generated=True,
            )
            scope.full_clean()
            scope.save()

            grant = MembershipGrant(
                membership=membership,
                role=owner_role,
                scope=scope,
                starts_at=now,
                is_active=True,
            )
            grant.full_clean()
            grant.save()

            subscription = create_trial_subscription(company=company, starts_at=now)

            return serialize_onboarding_result(
                company=company,
                membership=membership,
                role=owner_role,
                subscription=subscription,
            )
    except IntegrityError as exc:
        _raise_known_integrity_error(exc)
