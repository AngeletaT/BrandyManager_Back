from datetime import timedelta
from unittest.mock import patch

from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.authorization.models import PlatformRole, UserPlatformRole
from apps.billing.models import Subscription
from apps.billing.plans import TRIAL_DURATION_DAYS
from apps.onboarding.services import complete_client_onboarding
from apps.organizations.models import Company, CompanyMembership, MembershipGrant, ResourceScope, Site, Zone
from apps.organizations.tests import factories as f
from apps.playlists.models import Channel, Playlist
from apps.devices.models import Device


class OnboardingCompleteAPITests(APITestCase):
    def setUp(self):
        call_command("seed_initial_data", verbosity=0)
        self.user = self.create_verified_user()

    def create_verified_user(self, email="owner@example.com"):
        return f.User.objects.create_user(
            email=email,
            password="StrongPass123!",
            first_name="Ana",
            last_name="Ruiz",
            email_verified_at=timezone.now(),
        )

    def payload(self, **overrides):
        data = {
            "legal_name": "Ribera Retail S.L.",
            "trade_name": "Ribera Retail",
            "tax_id": "B98450112",
            "billing_email": "facturacion@riberaretail.es",
            "contact_email": "contacto@riberaretail.es",
            "phone": "+34960000000",
            "country_code": "es",
            "default_timezone": "Europe/Madrid",
            "default_language": "ES",
            "sector": "retail",
            "estimated_sites": "2-5",
        }
        data.update(overrides)
        return data

    def authenticate(self, user=None):
        self.client.force_authenticate(user=user or self.user)

    def login(self, user):
        return self.client.post(
            reverse("user-login"),
            {"email": user.email, "password": "StrongPass123!"},
            format="json",
        )

    def post_onboarding(self, payload=None):
        self.authenticate()
        return self.client.post(reverse("onboarding-complete"), payload or self.payload(), format="json")

    def test_onboarding_creates_required_account_pieces(self):
        response = self.post_onboarding()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        company = Company.objects.get()
        membership = CompanyMembership.objects.get()
        scope = ResourceScope.objects.get()
        grant = MembershipGrant.objects.get()
        subscription = Subscription.objects.get()

        self.assertEqual(company.status, Company.Status.TRIAL)
        self.assertEqual(company.tax_id, "B98450112")
        self.assertEqual(company.country_code, "ES")
        self.assertEqual(company.settings["onboarding"]["sector"], "retail")
        self.assertEqual(company.settings["onboarding"]["estimated_sites"], "2-5")
        self.assertEqual(membership.company_id, company.id)
        self.assertEqual(membership.user_id, self.user.id)
        self.assertEqual(membership.status, CompanyMembership.Status.ACTIVE)
        self.assertIsNotNone(membership.accepted_at)
        self.assertEqual(scope.company_id, company.id)
        self.assertEqual(scope.scope_type, ResourceScope.ScopeType.COMPANY)
        self.assertEqual(grant.membership_id, membership.id)
        self.assertEqual(grant.scope_id, scope.id)
        self.assertEqual(grant.role.code, "OWNER")
        self.assertEqual(subscription.company_id, company.id)
        self.assertEqual(subscription.status, Subscription.Status.TRIAL)
        self.assertEqual(subscription.plan.code, "STANDARD")

        body = response.data
        self.assertEqual(body["company"]["status"], "TRIAL")
        self.assertEqual(body["membership"]["status"], "ACTIVE")
        self.assertEqual(body["company_role"]["code"], "OWNER")
        self.assertEqual(body["subscription"]["plan_code"], "STANDARD")
        self.assertTrue(body["subscription"]["functional_access"])
        self.assertIsNone(body["subscription"]["block_reason"])
        self.assertEqual(body["next_step"], "APP")

    def test_owner_is_assigned_on_company_scope(self):
        self.post_onboarding()

        grant = MembershipGrant.objects.select_related("scope", "role").get()

        self.assertEqual(grant.role.code, "OWNER")
        self.assertEqual(grant.scope.scope_type, ResourceScope.ScopeType.COMPANY)

    def test_standard_trial_lasts_seven_days(self):
        self.post_onboarding()

        subscription = Subscription.objects.get()

        self.assertEqual(subscription.trial_ends_at - subscription.trial_started_at, timedelta(days=TRIAL_DURATION_DAYS))
        self.assertEqual(subscription.current_period_end, subscription.trial_ends_at)

    def test_payload_cannot_change_role_or_plan(self):
        response = self.post_onboarding(
            self.payload(
                company_role="MANAGER",
                role="admin",
                platform_role="SUPERADMIN",
                plan="PREMIUM",
                status="ACTIVE",
                trial_ends_at="2099-01-01T00:00:00Z",
            )
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["company_role"]["code"], "OWNER")
        self.assertEqual(response.data["subscription"]["plan_code"], "STANDARD")
        self.assertEqual(Subscription.objects.get().plan.code, "STANDARD")
        self.assertFalse(self.user.platform_roles.exists())

    def test_unverified_user_cannot_complete_onboarding(self):
        user = f.User.objects.create_user(email="pending@example.com", password="StrongPass123!")
        self.client.force_authenticate(user=user)

        response = self.client.post(reverse("onboarding-complete"), self.payload(tax_id="B98450113"), format="json")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["error"]["code"], "email_not_verified")
        self.assertFalse(Company.objects.exists())

    def test_user_with_membership_cannot_repeat_onboarding(self):
        self.post_onboarding()

        response = self.post_onboarding(self.payload(tax_id="B98450114"))

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["error"]["code"], "onboarding_already_completed")
        self.assertEqual(Company.objects.count(), 1)
        self.assertEqual(CompanyMembership.objects.count(), 1)

    def test_internal_user_cannot_complete_onboarding(self):
        role = PlatformRole.objects.get(code="SUPPORT_AGENT")
        UserPlatformRole.objects.create(user=self.user, role=role)

        response = self.post_onboarding()

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["error"]["code"], "onboarding_not_allowed")
        self.assertFalse(Company.objects.exists())

    def test_inactive_user_cannot_complete_onboarding(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])

        response = self.post_onboarding()

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["error"]["code"], "user_inactive")
        self.assertFalse(Company.objects.exists())

    def test_duplicate_tax_id_fails_without_partial_data(self):
        first_response = self.post_onboarding(self.payload(tax_id=" b98450112 "))
        other_user = self.create_verified_user("other-owner@example.com")
        self.client.force_authenticate(user=other_user)

        second_response = self.client.post(
            reverse("onboarding-complete"),
            self.payload(tax_id="B98450112"),
            format="json",
        )

        self.assertEqual(first_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second_response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(second_response.data["error"]["code"], "company_tax_id_already_registered")
        self.assertEqual(Company.objects.count(), 1)
        self.assertEqual(CompanyMembership.objects.count(), 1)
        self.assertEqual(ResourceScope.objects.count(), 1)
        self.assertEqual(MembershipGrant.objects.count(), 1)
        self.assertEqual(Subscription.objects.count(), 1)

    def test_subscription_failure_rolls_back_all_created_entities(self):
        with patch("apps.onboarding.services.create_trial_subscription", side_effect=RuntimeError("billing failed")):
            with self.assertRaises(RuntimeError):
                complete_client_onboarding(user=self.user, data=self.payload())

        self.assertFalse(Company.objects.exists())
        self.assertFalse(CompanyMembership.objects.exists())
        self.assertFalse(ResourceScope.objects.exists())
        self.assertFalse(MembershipGrant.objects.exists())
        self.assertFalse(Subscription.objects.exists())

    def test_repeated_requests_do_not_duplicate_entities(self):
        first_response = self.post_onboarding()
        second_response = self.post_onboarding()

        self.assertEqual(first_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second_response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(Company.objects.count(), 1)
        self.assertEqual(CompanyMembership.objects.count(), 1)
        self.assertEqual(ResourceScope.objects.count(), 1)
        self.assertEqual(MembershipGrant.objects.count(), 1)
        self.assertEqual(Subscription.objects.count(), 1)

    def test_me_changes_from_client_pending_to_client_after_onboarding(self):
        login_response = self.login(self.user)
        access = login_response.data["access"]

        before = self.client.get(reverse("user-me"), HTTP_AUTHORIZATION=f"Bearer {access}")
        onboarding_response = self.client.post(
            reverse("onboarding-complete"),
            self.payload(),
            HTTP_AUTHORIZATION=f"Bearer {access}",
            format="json",
        )
        after = self.client.get(reverse("user-me"), HTTP_AUTHORIZATION=f"Bearer {access}")

        self.assertEqual(before.data["context"]["access_type"], "client_pending")
        self.assertEqual(onboarding_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(after.data["context"]["access_type"], "client")
        self.assertFalse(after.data["context"]["onboarding_required"])
        self.assertEqual(after.data["context"]["company_role"]["code"], "OWNER")
        self.assertEqual(after.data["context"]["subscription"]["plan_code"], "STANDARD")
        self.assertTrue(after.data["context"]["functional_access"])
        self.assertEqual(after.data["context"]["next_step"], "APP")

    def test_onboarding_does_not_create_later_phase_entities(self):
        self.post_onboarding()

        self.assertFalse(Site.objects.exists())
        self.assertFalse(Zone.objects.exists())
        self.assertFalse(Playlist.objects.exists())
        self.assertFalse(Channel.objects.exists())
        self.assertFalse(Device.objects.exists())

    def test_invalid_timezone_is_rejected(self):
        response = self.post_onboarding(self.payload(default_timezone="Europe/Atlantis"))

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Company.objects.exists())

    def test_tax_id_is_unique_at_database_level(self):
        self.post_onboarding(self.payload(tax_id="B98450112"))
        other_company = Company(
            legal_name="Duplicada S.L.",
            trade_name="Duplicada",
            tax_id=" b98450112 ",
            billing_email="billing@example.com",
            contact_email="contact@example.com",
            country_code="es",
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                other_company.save(skip_validation=True)

        self.assertEqual(Company.objects.count(), 1)
