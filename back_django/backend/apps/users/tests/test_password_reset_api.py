from datetime import timedelta

from django.conf import settings
from django.core import mail
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.authorization.models import CompanyRole
from apps.billing.models import Subscription
from apps.billing.services import create_trial_subscription
from apps.organizations.models import CompanyMembership, MembershipGrant
from apps.organizations.tests import factories as f
from apps.users.models import UserActionToken
from apps.users.services import create_email_verification_token, create_password_reset_token_for_email


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    FRONTEND_BASE_URL="http://localhost:5173",
    BM_REFRESH_COOKIE_NAME="bm_refresh",
    BM_REFRESH_COOKIE_SECURE=False,
    BM_REFRESH_COOKIE_SAMESITE="Lax",
    BM_REFRESH_COOKIE_PATH="/api/users/",
)
class PasswordResetAPITests(APITestCase):
    def create_verified_user(self, email="client@example.com"):
        return f.User.objects.create_user(
            email=email,
            password="StrongPass123!",
            first_name="Ana",
            last_name="Ruiz",
            email_verified_at=timezone.now(),
        )

    def extract_token_from_last_email(self):
        return mail.outbox[-1].body.split("token=", 1)[1].split()[0]

    def test_request_always_returns_accepted(self):
        response = self.client.post(
            reverse("user-password-reset-request"),
            {"email": "missing@example.com"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(response.data, {"status": "accepted"})

    def test_missing_email_does_not_create_token_or_email(self):
        response = self.client.post(
            reverse("user-password-reset-request"),
            {"email": "missing@example.com"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(UserActionToken.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_existing_active_email_creates_token_and_email_with_reset_url(self):
        user = self.create_verified_user()

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("user-password-reset-request"),
                {"email": user.email},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(UserActionToken.objects.filter(user=user, purpose=UserActionToken.Purpose.RESET_PASSWORD).count(), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("http://localhost:5173/reset-password?token=", mail.outbox[0].body)
        raw_token = self.extract_token_from_last_email()
        self.assertFalse(UserActionToken.objects.filter(token_hash=raw_token).exists())

    def test_request_revokes_previous_reset_token_when_rate_limit_allows(self):
        user = self.create_verified_user()
        first_token, _ = create_password_reset_token_for_email(email=user.email)
        UserActionToken.objects.filter(pk=first_token.pk).update(created_at=timezone.now() - timedelta(minutes=3))

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("user-password-reset-request"),
                {"email": user.email},
                format="json",
            )
        first_token.refresh_from_db()

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertIsNotNone(first_token.revoked_at)
        self.assertEqual(UserActionToken.objects.filter(user=user, purpose=UserActionToken.Purpose.RESET_PASSWORD).count(), 2)
        self.assertEqual(len(mail.outbox), 1)

    def test_request_is_rate_limited_without_revealing_state(self):
        user = self.create_verified_user()
        create_password_reset_token_for_email(email=user.email)

        response = self.client.post(
            reverse("user-password-reset-request"),
            {"email": user.email},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(UserActionToken.objects.filter(user=user, purpose=UserActionToken.Purpose.RESET_PASSWORD).count(), 1)
        self.assertEqual(len(mail.outbox), 0)

    def test_validate_does_not_consume_token(self):
        user = self.create_verified_user()
        token, raw_token = create_password_reset_token_for_email(email=user.email)

        response = self.client.post(
            reverse("user-password-reset-validate"),
            {"token": raw_token},
            format="json",
        )
        token.refresh_from_db()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"valid": True})
        self.assertIsNone(token.consumed_at)

    def test_validate_returns_false_for_invalid_token(self):
        response = self.client.post(
            reverse("user-password-reset-validate"),
            {"token": "not-valid"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"valid": False})

    def test_confirm_changes_password_and_consumes_token(self):
        user = self.create_verified_user()
        token, raw_token = create_password_reset_token_for_email(email=user.email)

        response = self.client.post(
            reverse("user-password-reset-confirm"),
            {
                "token": raw_token,
                "password": "NuevaPassword123!",
                "password_confirmation": "NuevaPassword123!",
            },
            format="json",
        )
        user.refresh_from_db()
        token.refresh_from_db()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"status": "password_updated"})
        self.assertTrue(user.check_password("NuevaPassword123!"))
        self.assertIsNotNone(token.consumed_at)

    def test_reused_expired_revoked_or_wrong_purpose_token_fails(self):
        expired_user = self.create_verified_user("expired-reset@example.com")
        revoked_user = self.create_verified_user("revoked-reset@example.com")
        consumed_user = self.create_verified_user("consumed-reset@example.com")
        wrong_purpose_user = self.create_verified_user("wrong-purpose@example.com")
        expired_token, expired_raw = create_password_reset_token_for_email(email=expired_user.email)
        UserActionToken.objects.filter(pk=expired_token.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        revoked_token, revoked_raw = create_password_reset_token_for_email(email=revoked_user.email)
        UserActionToken.objects.filter(pk=revoked_token.pk).update(revoked_at=timezone.now())
        _, consumed_raw = create_password_reset_token_for_email(email=consumed_user.email)
        self.client.post(
            reverse("user-password-reset-confirm"),
            {
                "token": consumed_raw,
                "password": "NuevaPassword123!",
                "password_confirmation": "NuevaPassword123!",
            },
            format="json",
        )
        _, wrong_purpose_raw = create_email_verification_token(user=wrong_purpose_user)

        for raw_token in (consumed_raw, expired_raw, revoked_raw, wrong_purpose_raw):
            response = self.client.post(
                reverse("user-password-reset-confirm"),
                {
                    "token": raw_token,
                    "password": "OtraPassword123!",
                    "password_confirmation": "OtraPassword123!",
                },
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(response.data["error"]["code"], "password_reset_token_invalid")

    def test_password_mismatch_fails(self):
        user = self.create_verified_user()
        _, raw_token = create_password_reset_token_for_email(email=user.email)

        response = self.client.post(
            reverse("user-password-reset-confirm"),
            {
                "token": raw_token,
                "password": "NuevaPassword123!",
                "password_confirmation": "DistintaPassword123!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("password_confirmation", response.data["error"]["fields"])

    def test_weak_password_fails(self):
        user = self.create_verified_user()
        _, raw_token = create_password_reset_token_for_email(email=user.email)

        response = self.client.post(
            reverse("user-password-reset-confirm"),
            {
                "token": raw_token,
                "password": "123",
                "password_confirmation": "123",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("password", response.data["error"]["fields"])

    def test_previous_access_and_refresh_are_invalid_after_password_change(self):
        user = self.create_verified_user()
        login_response = self.client.post(
            reverse("user-login"),
            {"email": user.email, "password": "StrongPass123!"},
            format="json",
        )
        old_access = login_response.data["access"]
        old_refresh = login_response.cookies[settings.BM_REFRESH_COOKIE_NAME].value
        _, raw_token = create_password_reset_token_for_email(email=user.email)

        confirm_response = self.client.post(
            reverse("user-password-reset-confirm"),
            {
                "token": raw_token,
                "password": "NuevaPassword123!",
                "password_confirmation": "NuevaPassword123!",
            },
            format="json",
        )
        self.assertEqual(confirm_response.status_code, status.HTTP_200_OK)

        me_response = self.client.get(reverse("user-me"), HTTP_AUTHORIZATION=f"Bearer {old_access}")
        self.assertEqual(me_response.status_code, status.HTTP_401_UNAUTHORIZED)

        self.client.cookies[settings.BM_REFRESH_COOKIE_NAME] = old_refresh
        refresh_response = self.client.post(reverse("user-token-refresh"), HTTP_ORIGIN="http://localhost:5173")
        self.assertEqual(refresh_response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(refresh_response.data["error"]["code"], "session_expired")

    def test_login_works_with_new_password_after_reset(self):
        user = self.create_verified_user()
        _, raw_token = create_password_reset_token_for_email(email=user.email)
        self.client.post(
            reverse("user-password-reset-confirm"),
            {
                "token": raw_token,
                "password": "NuevaPassword123!",
                "password_confirmation": "NuevaPassword123!",
            },
            format="json",
        )

        response = self.client.post(
            reverse("user-login"),
            {"email": user.email, "password": "NuevaPassword123!"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)

    def test_password_reset_does_not_alter_company_membership_roles_or_subscription(self):
        call_command("seed_initial_data", verbosity=0)
        user = self.create_verified_user("owner-reset@example.com")
        company = f.company("reset-company")
        membership = f.membership(company, user)
        role = CompanyRole.objects.get(company=None, code="OWNER")
        scope = f.scope(company)
        grant = MembershipGrant.objects.create(membership=membership, role=role, scope=scope)
        subscription = create_trial_subscription(company=company)
        _, raw_token = create_password_reset_token_for_email(email=user.email)

        response = self.client.post(
            reverse("user-password-reset-confirm"),
            {
                "token": raw_token,
                "password": "NuevaPassword123!",
                "password_confirmation": "NuevaPassword123!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(CompanyMembership.objects.filter(pk=membership.pk, company=company, user=user).exists())
        self.assertTrue(MembershipGrant.objects.filter(pk=grant.pk, membership=membership, role=role, is_active=True).exists())
        self.assertTrue(Subscription.objects.filter(pk=subscription.pk, company=company).exists())
