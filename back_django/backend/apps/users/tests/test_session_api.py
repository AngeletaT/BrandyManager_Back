from datetime import timedelta

from django.conf import settings
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.authorization.models import CompanyRole, PlatformRole, UserPlatformRole
from apps.billing.services import create_trial_subscription
from apps.organizations.models import MembershipGrant
from apps.organizations.tests import factories as f


@override_settings(
    BM_REFRESH_COOKIE_NAME="bm_refresh",
    BM_REFRESH_COOKIE_SECURE=False,
    BM_REFRESH_COOKIE_SAMESITE="Lax",
    BM_REFRESH_COOKIE_PATH="/api/users/",
    CORS_ALLOW_CREDENTIALS=True,
    CORS_ALLOWED_ORIGINS=["http://localhost:5173"],
    CSRF_TRUSTED_ORIGINS=["http://localhost:5173"],
)
class UserSessionAPITests(APITestCase):
    def test_cors_credentials_are_enabled_for_configured_origins(self):
        self.assertTrue(settings.CORS_ALLOW_CREDENTIALS)
        self.assertIn("http://localhost:5173", settings.CORS_ALLOWED_ORIGINS)

    def create_verified_user(self, email="client@example.com"):
        return f.User.objects.create_user(
            email=email,
            password="StrongPass123!",
            first_name="Ana",
            last_name="Ruiz",
            email_verified_at=timezone.now(),
        )

    def login(self, user):
        return self.client.post(
            reverse("user-login"),
            {"email": user.email, "password": "StrongPass123!"},
            format="json",
        )

    def test_login_sets_http_only_cookie_and_returns_access_without_refresh_json(self):
        user = self.create_verified_user()

        response = self.login(user)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertNotIn("refresh", response.data)
        cookie = response.cookies[settings.BM_REFRESH_COOKIE_NAME]
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Lax")
        self.assertEqual(cookie["path"], "/api/users/")
        self.assertFalse(bool(cookie["secure"]))

    @override_settings(BM_REFRESH_COOKIE_SECURE=True)
    def test_cookie_secure_attribute_is_configurable_for_production(self):
        user = self.create_verified_user("secure@example.com")

        response = self.login(user)

        self.assertTrue(response.cookies[settings.BM_REFRESH_COOKIE_NAME]["secure"])

    def test_refresh_rotates_cookie_and_invalidates_previous_refresh(self):
        user = self.create_verified_user()
        login_response = self.login(user)
        old_refresh = login_response.cookies[settings.BM_REFRESH_COOKIE_NAME].value

        refresh_response = self.client.post(reverse("user-token-refresh"), HTTP_ORIGIN="http://localhost:5173")
        new_refresh = refresh_response.cookies[settings.BM_REFRESH_COOKIE_NAME].value

        self.assertEqual(refresh_response.status_code, status.HTTP_200_OK)
        self.assertIn("access", refresh_response.data)
        self.assertNotEqual(old_refresh, new_refresh)

        old_client = APIClient()
        old_client.cookies[settings.BM_REFRESH_COOKIE_NAME] = old_refresh
        invalid_response = old_client.post(reverse("user-token-refresh"), HTTP_ORIGIN="http://localhost:5173")

        self.assertEqual(invalid_response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(invalid_response.data["error"]["code"], "session_expired")

    def test_refresh_without_cookie_returns_session_expired(self):
        response = self.client.post(reverse("user-token-refresh"), HTTP_ORIGIN="http://localhost:5173")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["error"]["code"], "session_expired")

    def test_refresh_rejects_untrusted_origin(self):
        user = self.create_verified_user()
        self.login(user)

        response = self.client.post(reverse("user-token-refresh"), HTTP_ORIGIN="https://evil.example")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["error"]["code"], "origin_not_trusted")

    def test_logout_invalidates_and_deletes_cookie_idempotently(self):
        user = self.create_verified_user()
        self.login(user)

        response = self.client.post(reverse("user-logout"), HTTP_ORIGIN="http://localhost:5173")
        second_response = self.client.post(reverse("user-logout"), HTTP_ORIGIN="http://localhost:5173")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(second_response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(response.cookies[settings.BM_REFRESH_COOKIE_NAME].value, "")
        self.assertEqual(response.cookies[settings.BM_REFRESH_COOKIE_NAME]["path"], "/api/users/")

    def test_me_rejects_invalid_access_token(self):
        response = self.client.get(reverse("user-me"), HTTP_AUTHORIZATION="Bearer invalid-token")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_me_returns_client_pending_context(self):
        user = self.create_verified_user()
        login_response = self.login(user)

        response = self.client.get(
            reverse("user-me"),
            HTTP_AUTHORIZATION=f"Bearer {login_response.data['access']}",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn("access", response.data)
        self.assertEqual(response.data["context"]["access_type"], "client_pending")
        self.assertTrue(response.data["context"]["onboarding_required"])
        self.assertEqual(response.data["context"]["next_step"], "ONBOARDING")

    def test_me_returns_internal_admin_context_without_company_membership(self):
        user = self.create_verified_user("admin@example.com")
        role = PlatformRole.objects.create(code="SUPPORT_AGENT", name="Support Agent", is_system=True)
        UserPlatformRole.objects.create(user=user, role=role)
        login_response = self.login(user)

        response = self.client.get(
            reverse("user-me"),
            HTTP_AUTHORIZATION=f"Bearer {login_response.data['access']}",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["context"]["access_type"], "internal_admin")
        self.assertIsNone(response.data["context"]["company"])
        self.assertTrue(response.data["context"]["functional_access"])
        self.assertEqual(response.data["context"]["next_step"], "ADMIN")

    def test_client_payload_cannot_make_user_internal_admin(self):
        user = self.create_verified_user("payload@example.com")

        response = self.client.post(
            reverse("user-login"),
            {
                "email": user.email,
                "password": "StrongPass123!",
                "access_type": "internal_admin",
                "role": "admin",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["context"]["access_type"], "client_pending")

    def test_me_returns_client_context_with_active_trial(self):
        call_command("seed_initial_data", verbosity=0)
        user = self.create_verified_user("owner@example.com")
        company = f.company("session-active")
        membership = f.membership(company, user)
        role = CompanyRole.objects.get(company=None, code="OWNER")
        scope = f.scope(company)
        MembershipGrant.objects.create(membership=membership, role=role, scope=scope)
        subscription = create_trial_subscription(company=company)
        login_response = self.login(user)

        response = self.client.get(
            reverse("user-me"),
            HTTP_AUTHORIZATION=f"Bearer {login_response.data['access']}",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        context = response.data["context"]
        self.assertEqual(context["access_type"], "client")
        self.assertFalse(context["onboarding_required"])
        self.assertEqual(context["company"]["id"], str(company.id))
        self.assertEqual(context["membership"]["id"], str(membership.id))
        self.assertEqual(context["company_role"]["code"], "OWNER")
        self.assertEqual(context["subscription"]["id"], str(subscription.id))
        self.assertEqual(context["subscription"]["plan_code"], "STANDARD")
        self.assertTrue(context["subscription"]["functional_access"])
        self.assertTrue(context["functional_access"])
        self.assertIsNone(context["block_reason"])
        self.assertEqual(context["next_step"], "APP")

    def test_context_reflects_expired_trial_without_functional_access(self):
        call_command("seed_initial_data", verbosity=0)
        user = self.create_verified_user("expired-owner@example.com")
        company = f.company("session-expired")
        membership = f.membership(company, user)
        role = CompanyRole.objects.get(company=None, code="OWNER")
        scope = f.scope(company)
        MembershipGrant.objects.create(membership=membership, role=role, scope=scope)
        create_trial_subscription(company=company, starts_at=timezone.now() - timedelta(days=8))
        login_response = self.login(user)

        response = self.client.get(
            reverse("user-me"),
            HTTP_AUTHORIZATION=f"Bearer {login_response.data['access']}",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        context = response.data["context"]
        self.assertFalse(context["functional_access"])
        self.assertEqual(context["block_reason"], "trial_expired")
        self.assertEqual(context["subscription"]["block_reason"], "trial_expired")
        self.assertEqual(context["next_step"], "BILLING")
