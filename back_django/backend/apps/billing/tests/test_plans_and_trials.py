from datetime import timedelta

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.billing.models import Plan, Subscription
from apps.billing.plans import OFFICIAL_PLAN_DEFINITIONS, TRIAL_DURATION_DAYS
from apps.billing.selectors import get_subscription_effective_limits, subscription_has_functional_access
from apps.billing.services import create_trial_subscription
from apps.organizations.tests import factories as f


class PlanAndTrialTests(TestCase):
    def test_official_plans_are_created_without_duplicates(self):
        call_command("seed_initial_data", verbosity=0)
        call_command("seed_initial_data", verbosity=0)

        for code in OFFICIAL_PLAN_DEFINITIONS:
            self.assertEqual(Plan.objects.filter(code=code).count(), 1)

    def test_plan_limits_are_recovered_from_central_features(self):
        call_command("seed_initial_data", verbosity=0)

        plan = Plan.objects.get(code="BASIC")

        self.assertEqual(plan.features["limits"]["sites"], 2)
        self.assertEqual(plan.features["limits"]["devices"], 4)

    def test_standard_trial_lasts_exactly_seven_days(self):
        call_command("seed_initial_data", verbosity=0)
        starts_at = timezone.now()
        subscription = create_trial_subscription(company=f.company("trial"), starts_at=starts_at)

        self.assertEqual(subscription.plan.code, "STANDARD")
        self.assertEqual(subscription.trial_ends_at - subscription.trial_started_at, timedelta(days=TRIAL_DURATION_DAYS))

    def test_expired_trial_has_no_functional_access(self):
        call_command("seed_initial_data", verbosity=0)
        starts_at = timezone.now() - timedelta(days=8)
        subscription = create_trial_subscription(company=f.company("expired-trial"), starts_at=starts_at)

        self.assertFalse(subscription_has_functional_access(subscription=subscription, at=timezone.now()))
        self.assertEqual(subscription.access_block_reason(at=timezone.now()), "trial_expired")

    def test_subscription_effective_limits_use_plan_snapshot(self):
        call_command("seed_initial_data", verbosity=0)
        subscription = create_trial_subscription(company=f.company("limits"))
        subscription.plan_snapshot["limits"]["sites"] = 99

        self.assertEqual(get_subscription_effective_limits(subscription=subscription)["sites"], 99)

    def test_non_trial_blocked_status_has_no_functional_access(self):
        company = f.company("past-due")
        now = timezone.now()
        subscription = Subscription.objects.create(
            company=company,
            plan=None,
            status=Subscription.Status.PAST_DUE,
            started_at=now,
            current_period_start=now,
            current_period_end=now + timedelta(days=30),
            license_quantity=1,
            unit_price="0.00",
            currency="EUR",
        )

        self.assertFalse(subscription.has_functional_access())
        self.assertEqual(subscription.access_block_reason(), "past_due")
