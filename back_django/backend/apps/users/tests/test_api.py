from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.organizations.models import CompanyMembership
from apps.users.models import UserActionToken
from apps.users.services import create_email_verification_token, create_user_action_token


UserModel = get_user_model()


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", FRONTEND_BASE_URL="http://localhost:5173")
class UserAuthAPITests(APITestCase):
    def extract_token_from_last_email(self):
        body = mail.outbox[-1].body
        return body.split("token=", 1)[1].split()[0]

    def test_register_creates_pending_client_user_without_tokens(self):
        response = self.client.post(
            reverse("user-register"),
            {
                "email": "client@example.com",
                "password": "StrongPass123!",
                "first_name": "Client",
                "last_name": "Example",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            response.data,
            {
                "status": "verification_required",
                "email": "client@example.com",
                "next_step": "VERIFY_EMAIL",
            },
        )
        self.assertNotIn("access", response.data)
        self.assertNotIn("refresh", response.data)

        user = UserModel.objects.get(email="client@example.com")
        self.assertTrue(user.check_password("StrongPass123!"))
        self.assertIsNone(user.email_verified_at)
        self.assertFalse(user.platform_roles.filter(revoked_at__isnull=True).exists())
        self.assertFalse(CompanyMembership.objects.filter(user=user).exists())

    def test_register_rejects_duplicate_email(self):
        UserModel.objects.create_user(
            email="client@example.com",
            password="StrongPass123!",
        )

        response = self.client.post(
            reverse("user-register"),
            {
                "email": "client@example.com",
                "password": "StrongPass123!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["error"]["code"], "email_already_registered")
        self.assertEqual(response.data["error"]["fields"]["email"], ["Ya existe una cuenta con este email."])

    def test_register_ignores_unknown_role_payload(self):
        response = self.client.post(
            reverse("user-register"),
            {
                "email": "client@example.com",
                "password": "StrongPass123!",
                "role": "admin",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertNotIn("role", response.data)
        user = UserModel.objects.get(email="client@example.com")
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.platform_roles.filter(revoked_at__isnull=True).exists())

    def test_login_returns_tokens(self):
        UserModel.objects.create_user(
            email="client@example.com",
            password="StrongPass123!",
            email_verified_at=timezone.now(),
        )

        response = self.client.post(
            reverse("user-login"),
            {
                "email": "client@example.com",
                "password": "StrongPass123!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["user"]["email"], "client@example.com")
        self.assertIn("access", response.data)
        self.assertNotIn("refresh", response.data)
        self.assertNotIn("tokens", response.data)
        self.assertIn(settings.BM_REFRESH_COOKIE_NAME, response.cookies)
        cookie = response.cookies[settings.BM_REFRESH_COOKIE_NAME]
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], settings.BM_REFRESH_COOKIE_SAMESITE)
        self.assertEqual(cookie["path"], settings.BM_REFRESH_COOKIE_PATH)

    def test_login_rejects_unverified_user(self):
        UserModel.objects.create_user(
            email="client@example.com",
            password="StrongPass123!",
        )

        response = self.client.post(
            reverse("user-login"),
            {
                "email": "client@example.com",
                "password": "StrongPass123!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["error"]["code"], "email_not_verified")
        self.assertEqual(response.data["error"]["next_step"], "VERIFY_EMAIL")

    def test_login_rejects_invalid_credentials(self):
        response = self.client.post(
            reverse("user-login"),
            {
                "email": "missing@example.com",
                "password": "StrongPass123!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["error"]["code"], "invalid_credentials")

    def test_login_rejects_inactive_user_with_stable_error_code(self):
        UserModel.objects.create_user(
            email="inactive@example.com",
            password="StrongPass123!",
            email_verified_at=timezone.now(),
            is_active=False,
        )

        response = self.client.post(
            reverse("user-login"),
            {
                "email": "inactive@example.com",
                "password": "StrongPass123!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["error"]["code"], "user_inactive")

    def test_register_sends_verification_email_with_frontend_url_and_raw_token(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("user-register"),
                {
                    "email": "client@example.com",
                    "password": "StrongPass123!",
                },
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("http://localhost:5173/verificar-email?token=", mail.outbox[0].body)
        raw_token = self.extract_token_from_last_email()
        self.assertFalse(UserActionToken.objects.filter(token_hash=raw_token).exists())

    def test_resend_does_not_reveal_missing_email(self):
        response = self.client.post(
            reverse("user-email-verification-resend"),
            {"email": "missing@example.com"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(response.data, {"status": "accepted"})
        self.assertEqual(len(mail.outbox), 0)

    def test_resend_revokes_previous_token_and_sends_new_one(self):
        user = UserModel.objects.create_user(email="client@example.com", password="StrongPass123!")
        first_token, _ = create_email_verification_token(user=user)
        UserActionToken.objects.filter(pk=first_token.pk).update(created_at=timezone.now() - timedelta(minutes=3))

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("user-email-verification-resend"),
                {"email": "client@example.com"},
                format="json",
            )
        first_token.refresh_from_db()

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertIsNotNone(first_token.revoked_at)
        self.assertEqual(UserActionToken.objects.filter(user=user, purpose=UserActionToken.Purpose.VERIFY_EMAIL).count(), 2)
        self.assertEqual(len(mail.outbox), 1)

    def test_resend_does_not_create_token_for_verified_email(self):
        user = UserModel.objects.create_user(
            email="client@example.com",
            password="StrongPass123!",
            email_verified_at=timezone.now(),
        )

        response = self.client.post(
            reverse("user-email-verification-resend"),
            {"email": "client@example.com"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertFalse(UserActionToken.objects.filter(user=user).exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_resend_is_rate_limited_without_revealing_state(self):
        user = UserModel.objects.create_user(email="client@example.com", password="StrongPass123!")
        create_email_verification_token(user=user)

        response = self.client.post(
            reverse("user-email-verification-resend"),
            {"email": "client@example.com"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(UserActionToken.objects.filter(user=user).count(), 1)
        self.assertEqual(len(mail.outbox), 0)

    def test_confirm_valid_token_marks_email_without_company_or_internal_role(self):
        user = UserModel.objects.create_user(email="client@example.com", password="StrongPass123!")
        _, raw_token = create_email_verification_token(user=user)

        response = self.client.post(
            reverse("user-email-verification-confirm"),
            {"token": raw_token},
            format="json",
        )
        user.refresh_from_db()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"status": "verified", "next_step": "ONBOARDING"})
        self.assertIsNotNone(user.email_verified_at)
        self.assertFalse(CompanyMembership.objects.filter(user=user).exists())
        self.assertFalse(user.platform_roles.filter(revoked_at__isnull=True).exists())

    def test_confirm_invalid_expired_revoked_or_consumed_token_fails(self):
        expired_user = UserModel.objects.create_user(email="expired@example.com", password="StrongPass123!")
        revoked_user = UserModel.objects.create_user(email="revoked@example.com", password="StrongPass123!")
        consumed_user = UserModel.objects.create_user(email="consumed@example.com", password="StrongPass123!")
        _, expired_raw = create_user_action_token(
            user=expired_user,
            purpose=UserActionToken.Purpose.VERIFY_EMAIL,
            ttl=-timedelta(seconds=1),
        )
        revoked_token, revoked_raw = create_email_verification_token(user=revoked_user)
        UserActionToken.objects.filter(pk=revoked_token.pk).update(revoked_at=timezone.now())
        _, consumed_raw = create_email_verification_token(user=consumed_user)
        self.client.post(reverse("user-email-verification-confirm"), {"token": consumed_raw}, format="json")

        for raw_token in ("not-a-valid-token", expired_raw, revoked_raw, consumed_raw):
            response = self.client.post(
                reverse("user-email-verification-confirm"),
                {"token": raw_token},
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(response.data["error"]["code"], "verification_token_invalid")
