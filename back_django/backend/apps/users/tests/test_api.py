from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase


UserModel = get_user_model()


class UserAuthAPITests(APITestCase):
    def test_register_creates_client_user_and_returns_tokens(self):
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
        self.assertEqual(response.data["user"]["email"], "client@example.com")
        self.assertIn("access", response.data["tokens"])
        self.assertIn("refresh", response.data["tokens"])

        user = UserModel.objects.get(email="client@example.com")
        self.assertTrue(user.check_password("StrongPass123!"))

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

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("email", response.data)

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
        self.assertNotIn("role", response.data["user"])

    def test_login_returns_tokens(self):
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

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["user"]["email"], "client@example.com")
        self.assertIn("access", response.data["tokens"])
        self.assertIn("refresh", response.data["tokens"])

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
