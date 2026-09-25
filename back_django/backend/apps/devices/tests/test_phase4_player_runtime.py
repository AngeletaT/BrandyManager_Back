import uuid
from datetime import timedelta

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase
from rest_framework_simplejwt.tokens import AccessToken

from apps.devices.auth import issue_device_access_token
from apps.devices.models import Device, DeviceCommand, DeviceCredential, DeviceEvent, DeviceState
from apps.devices.services import create_device_command
from apps.organizations.tests import factories as f


@override_settings(BM_GO_SERVICE_TOKEN="go-service-test")
class Phase4PlayerRuntimeTests(APITestCase):
    def setUp(self):
        self.company = f.company("player-runtime")
        self.site = f.site(self.company, "player-site")
        self.zone = f.zone(self.company, self.site, "player-zone")
        self.device = Device.objects.create(
            company=self.company,
            zone=self.zone,
            hardware_id=f"web-{uuid.uuid4()}",
            code="PLAYER-01",
            name="Player",
            device_type=Device.DeviceType.DESKTOP_APP,
            status=Device.Status.OFFLINE,
            administrative_status=Device.AdministrativeStatus.ACTIVE,
            activation_status=Device.ActivationStatus.ACTIVATED,
        )
        DeviceState.objects.create(device=self.device, zone=self.zone)
        self.credential = DeviceCredential.objects.create(
            device=self.device,
            credential_id=str(uuid.uuid4()),
            secret_hash="not-a-plain-secret",
            expires_at=timezone.now() + timedelta(days=1),
        )
        token, _ = issue_device_access_token(device=self.device, credential=self.credential)
        self.client = APIClient()
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {token}",
            HTTP_X_BRANDYMANAGER_SERVICE_TOKEN="go-service-test",
        )

    def test_runtime_without_published_snapshot_is_explicit(self):
        response = self.client.get(reverse("player-runtime"))

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["reason"], "NO_PUBLISHED_CONFIGURATION")
        self.assertIsNone(response.data["manifest"])
        self.assertEqual(response.data["device"]["id"], str(self.device.id))

    def test_telemetry_is_idempotent_and_out_of_order_does_not_rewind_state(self):
        first_id = uuid.uuid4()
        now = timezone.now()
        response = self.client.post(
            reverse("player-telemetry"),
            {
                "events": [
                    {
                        "event_id": str(first_id),
                        "sequence": 2,
                        "occurred_at": now.isoformat(),
                        "event_type": "HEARTBEAT",
                        "playback_status": "PLAYING",
                        "position_ms": 200,
                    }
                ]
            },
            format="json",
        )
        duplicate = self.client.post(
            reverse("player-telemetry"),
            {
                "events": [
                    {
                        "event_id": str(first_id),
                        "sequence": 2,
                        "occurred_at": now.isoformat(),
                        "event_type": "HEARTBEAT",
                    },
                    {
                        "event_id": str(uuid.uuid4()),
                        "sequence": 1,
                        "occurred_at": now.isoformat(),
                        "event_type": "OFFLINE",
                    },
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(duplicate.status_code, status.HTTP_200_OK, duplicate.data)
        self.assertEqual(duplicate.data["duplicates"], 1)
        state = DeviceState.objects.get(device=self.device)
        self.assertEqual(state.last_sequence, 2)
        self.assertEqual(state.position_ms, 200)
        self.assertTrue(state.is_online)
        self.assertEqual(DeviceEvent.objects.filter(device=self.device).count(), 2)

    def test_commands_are_ordered_expire_and_acknowledge_idempotently(self):
        expired = create_device_command(
            device=self.device,
            command_type=DeviceCommand.CommandType.FORCE_SYNC,
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        superseded = create_device_command(
            device=self.device,
            command_type=DeviceCommand.CommandType.SET_VOLUME,
            payload={"volume": 20},
        )
        command = create_device_command(
            device=self.device,
            command_type=DeviceCommand.CommandType.SET_VOLUME,
            payload={"volume": 35},
        )

        delivered = self.client.get(reverse("player-commands"))
        self.assertEqual(delivered.status_code, status.HTTP_200_OK, delivered.data)
        self.assertEqual([item["command_id"] for item in delivered.data["commands"]], [str(command.id)])
        expired.refresh_from_db()
        superseded.refresh_from_db()
        self.assertEqual(expired.status, DeviceCommand.Status.EXPIRED)
        self.assertEqual(superseded.status, DeviceCommand.Status.CANCELLED)

        url = reverse("player-command-ack", kwargs={"command_id": command.id})
        first = self.client.post(url, {"status": "EXECUTED", "result": {"volume": 35}}, format="json")
        repeated = self.client.post(url, {"status": "EXECUTED", "result": {"volume": 35}}, format="json")
        self.assertEqual(first.status_code, status.HTTP_200_OK, first.data)
        self.assertEqual(repeated.status_code, status.HTTP_200_OK, repeated.data)

    def test_user_jwt_and_missing_service_token_are_rejected(self):
        user = f.user("not-a-device@example.com")
        user_token = str(AccessToken.for_user(user))
        user_client = APIClient()
        user_client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {user_token}",
            HTTP_X_BRANDYMANAGER_SERVICE_TOKEN="go-service-test",
        )
        self.assertEqual(user_client.get(reverse("player-runtime")).status_code, status.HTTP_401_UNAUTHORIZED)

        missing_service = APIClient()
        access, _ = issue_device_access_token(device=self.device, credential=self.credential)
        missing_service.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        self.assertEqual(missing_service.get(reverse("player-runtime")).status_code, status.HTTP_403_FORBIDDEN)

    def test_revoked_device_is_rejected_immediately(self):
        self.device.activation_status = Device.ActivationStatus.REVOKED
        self.device.save(update_fields=["activation_status"])
        response = self.client.get(reverse("player-runtime"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
