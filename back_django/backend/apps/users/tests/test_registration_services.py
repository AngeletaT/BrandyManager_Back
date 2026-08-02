from django.core import mail
from django.test import TestCase, override_settings

from apps.users.models import UserActionToken
from apps.users.services import register_client_user


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", FRONTEND_BASE_URL="http://localhost:5173")
class RegistrationServiceTests(TestCase):
    def test_verification_email_is_sent_only_after_transaction_commit(self):
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            user = register_client_user(
                data={
                    "email": "client@example.com",
                    "password": "StrongPass123!",
                    "first_name": "Ana",
                    "last_name": "Ruiz",
                }
            )

        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(len(callbacks), 1)

        callbacks[0]()

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("http://localhost:5173/verificar-email?token=", mail.outbox[0].body)
        raw_token = mail.outbox[0].body.split("token=", 1)[1].split()[0]
        self.assertFalse(UserActionToken.objects.filter(token_hash=raw_token).exists())
        self.assertEqual(UserActionToken.objects.filter(user=user).count(), 1)
