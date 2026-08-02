from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.authorization.models import UserPlatformRole
from apps.users.models import UserActionToken
from apps.users.services import (
    consume_user_action_token,
    create_email_verification_token,
    create_password_reset_token_for_email,
    create_user_action_token,
)
from apps.users.selectors import get_user_account_classification
from apps.organizations.tests import factories as f


class UserActionTokenTests(TestCase):
    def setUp(self):
        self.user = f.user("token-user@example.com")

    def test_expired_action_token_is_not_valid(self):
        action_token, _ = create_user_action_token(
            user=self.user,
            purpose=UserActionToken.Purpose.RESET_PASSWORD,
            ttl=timedelta(seconds=1),
        )

        self.assertFalse(action_token.is_valid(at=timezone.now() + timedelta(seconds=2)))

    def test_consumed_token_cannot_be_reused(self):
        _, raw_token = create_email_verification_token(user=self.user)

        consume_user_action_token(raw_token=raw_token, purpose=UserActionToken.Purpose.VERIFY_EMAIL)

        with self.assertRaises(ValidationError):
            consume_user_action_token(raw_token=raw_token, purpose=UserActionToken.Purpose.VERIFY_EMAIL)

    def test_original_token_is_not_stored_in_plain_text(self):
        action_token, raw_token = create_email_verification_token(user=self.user)

        self.assertNotEqual(action_token.token_hash, raw_token)
        self.assertFalse(UserActionToken.objects.filter(token_hash=raw_token).exists())

    def test_new_token_revokes_previous_active_token_for_same_purpose(self):
        first_token, _ = create_email_verification_token(user=self.user)
        second_token, _ = create_email_verification_token(user=self.user)

        first_token.refresh_from_db()

        self.assertIsNotNone(first_token.revoked_at)
        self.assertTrue(second_token.is_valid())

    def test_password_reset_for_missing_email_does_not_create_token(self):
        token, raw_token = create_password_reset_token_for_email(email="missing@example.com")

        self.assertIsNone(token)
        self.assertIsNone(raw_token)
        self.assertEqual(UserActionToken.objects.count(), 0)

    def test_email_verification_does_not_assign_internal_privileges(self):
        _, raw_token = create_email_verification_token(user=self.user)

        consume_user_action_token(raw_token=raw_token, purpose=UserActionToken.Purpose.VERIFY_EMAIL)
        self.user.refresh_from_db()

        self.assertIsNotNone(self.user.email_verified_at)
        self.assertFalse(UserPlatformRole.objects.filter(user=self.user, revoked_at__isnull=True).exists())
        self.assertEqual(get_user_account_classification(user=self.user), "client_pending")
