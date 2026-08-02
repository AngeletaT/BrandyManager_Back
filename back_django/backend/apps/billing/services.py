from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.billing.models import License, LicenseAssignment, Plan, Subscription
from apps.billing.plans import OFFICIAL_PLAN_DEFINITIONS, TRIAL_DURATION_DAYS, TRIAL_PLAN_CODE, build_plan_features


def build_plan_snapshot(*, plan):
    return {
        "code": plan.code,
        "name": plan.name,
        "billing_interval": plan.billing_interval,
        "unit_price": str(plan.base_price),
        "currency": plan.currency,
        "included_licenses": plan.included_licenses,
        "features": plan.features,
        "limits": plan.features.get("limits", {}),
        "pricing_status": plan.features.get("pricing_status", "provisional"),
    }


@transaction.atomic
def create_trial_subscription(*, company, starts_at=None):
    starts_at = starts_at or timezone.now()
    plan = Plan.objects.select_for_update().get(code=TRIAL_PLAN_CODE)
    definition = OFFICIAL_PLAN_DEFINITIONS[TRIAL_PLAN_CODE]
    trial_ends_at = starts_at + timedelta(days=TRIAL_DURATION_DAYS)

    return Subscription.objects.create(
        company=company,
        plan=plan,
        status=Subscription.Status.TRIAL,
        started_at=starts_at,
        current_period_start=starts_at,
        current_period_end=trial_ends_at,
        trial_started_at=starts_at,
        trial_ends_at=trial_ends_at,
        license_quantity=definition["included_licenses"],
        unit_price=plan.base_price,
        currency=plan.currency,
        plan_snapshot=build_plan_snapshot(plan=plan),
        commercial_terms={
            "trial_days": TRIAL_DURATION_DAYS,
            "payment_provider": None,
        },
    )


def upsert_official_plan(*, code):
    definition = OFFICIAL_PLAN_DEFINITIONS[code]
    return Plan.objects.update_or_create(
        code=code,
        defaults={
            "name": definition["name"],
            "description": definition["description"],
            "billing_interval": Plan.BillingInterval.MONTHLY,
            "base_price": definition["base_price"],
            "currency": definition["currency"],
            "included_licenses": definition["included_licenses"],
            "features": build_plan_features(code=code),
            "is_public": True,
            "is_active": True,
        },
    )


@transaction.atomic
def assign_license_to_zone(*, license_id, zone, assigned_by=None, reason=""):
    license_obj = License.objects.select_for_update().get(id=license_id)
    LicenseAssignment.objects.select_for_update().filter(zone=zone, unassigned_at__isnull=True)

    assignment = LicenseAssignment.objects.create(
        company=license_obj.company,
        license=license_obj,
        zone=zone,
        assigned_by=assigned_by,
        assigned_at=timezone.now(),
        reason=reason,
    )
    license_obj.status = License.Status.ASSIGNED
    license_obj.activated_at = license_obj.activated_at or assignment.assigned_at
    license_obj.save(update_fields=["status", "activated_at", "updated_at"])
    return assignment


@transaction.atomic
def unassign_license(*, assignment_id, unassigned_by=None, reason=""):
    assignment = LicenseAssignment.objects.select_for_update().select_related("license").get(id=assignment_id)
    if assignment.unassigned_at:
        return assignment

    assignment.unassigned_at = timezone.now()
    assignment.unassigned_by = unassigned_by
    assignment.reason = reason or assignment.reason
    assignment.save(update_fields=["unassigned_at", "unassigned_by", "reason"])

    license_obj = assignment.license
    license_obj.status = License.Status.AVAILABLE
    license_obj.save(update_fields=["status", "updated_at"])
    return assignment
