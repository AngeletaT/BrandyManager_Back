from datetime import timedelta

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase
from rest_framework_simplejwt.tokens import AccessToken

from apps.authorization.models import CompanyRole, CompanyRolePermission, Permission
from apps.authorization.services import get_company_scope, get_or_create_zone_scope
from apps.devices.models import (
    Device,
    DeviceActivation,
    DeviceCommand,
    DeviceCredential,
    DeviceEvent,
    DeviceZoneAssignment,
)
from apps.organizations.models import MembershipGrant
from apps.organizations.tests import factories as f


class DeviceApiTests(APITestCase):
    def setUp(self):
        self.company = f.company("devices")
        self.site = f.site(self.company, "main")
        self.zone = f.zone(self.company, self.site, "cashiers")
        self.user = f.user("owner-devices@example.com")
        self.user.email_verified_at = timezone.now()
        self.user.save(update_fields=["email_verified_at"])
        self.membership = f.membership(self.company, self.user)
        f.subscription(self.company)
        self.grant_permissions(
            "devices.view",
            "devices.manage",
            "playback.view",
            "playback.control",
            "playback.volume",
        )
        self.client.force_authenticate(self.user)

    def grant_permissions(self, *codes, scope=None):
        role = CompanyRole.objects.create(company=None, code=f"DEVICES_{CompanyRole.objects.count()}", name="Devices")
        for code in codes:
            permission, _ = Permission.objects.get_or_create(
                code=code,
                defaults={
                    "name": code,
                    "module": code.split(".")[0],
                    "permission_level": Permission.PermissionLevel.COMPANY,
                },
            )
            CompanyRolePermission.objects.create(role=role, permission=permission)
        MembershipGrant.objects.create(
            membership=self.membership,
            role=role,
            scope=scope or get_company_scope(company=self.company),
        )

    def create_device(self, **overrides):
        payload = {
            "name": "Reproductor cajas",
            "code": "CAJAS-01",
            "zone_id": str(self.zone.id),
            "device_type": "DESKTOP_APP",
        }
        payload.update(overrides)
        response = self.client.post(reverse("device-list"), payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        return response

    def test_create_assign_and_list_device(self):
        response = self.create_device()
        device = Device.objects.get(id=response.data["id"])

        self.assertEqual(device.zone_id, self.zone.id)
        self.assertEqual(device.activation_status, Device.ActivationStatus.PENDING)
        self.assertTrue(DeviceZoneAssignment.objects.filter(device=device, zone=self.zone, unassigned_at__isnull=True).exists())
        self.assertEqual(response.data["permissions"]["can_manage_activation"], True)

    def test_list_filters_by_site_and_derived_connectivity(self):
        online = Device.objects.get(id=self.create_device().data["id"])
        online.last_seen_at = timezone.now()
        online.save(update_fields=["last_seen_at", "updated_at"])
        other_site = f.site(self.company, "secondary")
        other_zone = f.zone(self.company, other_site, "secondary")
        self.create_device(name="Otro", code="OTHER-01", zone_id=str(other_zone.id))

        response = self.client.get(
            reverse("device-list"),
            {"site_id": str(self.site.id), "connectivity_status": "ONLINE"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], str(online.id))
        self.assertIn("usage", response.data)
        self.assertTrue(response.data["permissions"]["can_create"])

    def test_panel_lists_durable_commands_and_events(self):
        device = Device.objects.get(id=self.create_device().data["id"])
        command = DeviceCommand.objects.create(
            company=self.company,
            device=device,
            command_type=DeviceCommand.CommandType.FORCE_SYNC,
            created_by=self.user,
        )
        event = DeviceEvent.objects.create(
            company=self.company,
            device=device,
            event_type="PLAYBACK_ERROR",
            severity=DeviceEvent.Severity.ERROR,
            occurred_at=timezone.now(),
            error_code="decoder_failed",
        )

        commands = self.client.get(reverse("device-command-create", kwargs={"device_id": device.id}))
        events = self.client.get(reverse("device-event-list", kwargs={"device_id": device.id}))

        self.assertEqual(commands.status_code, status.HTTP_200_OK)
        self.assertEqual(commands.data["results"][0]["id"], str(command.id))
        self.assertEqual(events.status_code, status.HTTP_200_OK)
        self.assertEqual(events.data["results"][0]["id"], str(event.id))
        self.assertEqual(events.data["results"][0]["error_code"], "decoder_failed")

    def test_device_limit_is_enforced(self):
        subscription = f.subscription(self.company)
        subscription.plan.features = {"limits": {"devices": 1}}
        subscription.plan.save(update_fields=["features"])
        self.create_device()

        response = self.client.post(
            reverse("device-list"),
            {"name": "Otro", "code": "OTRO", "zone_id": str(self.zone.id)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["error"]["code"], "device_limit_reached")

    def test_change_zone_keeps_assignment_history_and_allows_multiple_zone_devices(self):
        second_zone = f.zone(self.company, self.site, "bakery")
        first = self.create_device()
        device = Device.objects.get(id=first.data["id"])
        self.create_device(name="Segundo", code="CAJAS-02")

        response = self.client.post(
            reverse("device-zone", kwargs={"device_id": device.id}),
            {"zone_id": str(second_zone.id), "expected_revision": device.configuration_version, "reason": "Cambio de ubicacion"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(DeviceZoneAssignment.objects.filter(device=device, unassigned_at__isnull=False).count(), 1)
        self.assertEqual(DeviceZoneAssignment.objects.filter(device=device, zone=second_zone, unassigned_at__isnull=True).count(), 1)

    def test_cannot_assign_device_to_another_company_zone(self):
        device = Device.objects.get(id=self.create_device().data["id"])
        other_company = f.company("other-devices")
        other_site = f.site(other_company, "other-site")
        other_zone = f.zone(other_company, other_site, "other-zone")

        response = self.client.post(
            reverse("device-zone", kwargs={"device_id": device.id}),
            {"zone_id": str(other_zone.id), "expected_revision": device.configuration_version},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_activation_code_is_hashed_single_use_and_rotates_cookie(self):
        device = Device.objects.get(id=self.create_device().data["id"])
        code_response = self.client.post(reverse("device-activation-code", kwargs={"device_id": device.id}), {}, format="json")
        self.assertEqual(code_response.status_code, status.HTTP_201_CREATED)
        raw_code = code_response.data["code"]
        activation = DeviceActivation.objects.get(device=device)
        self.assertNotEqual(activation.code_hash, raw_code)
        self.assertNotIn(raw_code.replace("-", ""), activation.code_hash)

        public_client = APIClient()
        validation = public_client.post(reverse("player-activation-validate"), {"code": raw_code}, format="json")
        self.assertEqual(validation.status_code, status.HTTP_200_OK, validation.data)
        completion = public_client.post(reverse("player-activation-complete"), {"code": raw_code}, format="json")
        self.assertEqual(completion.status_code, status.HTTP_200_OK, completion.data)
        self.assertIn("bm_device_refresh", completion.cookies)
        self.assertNotIn("refresh", completion.data)
        self.assertTrue(DeviceCredential.objects.filter(device=device, status=DeviceCredential.Status.ACTIVE).exists())

        repeated = public_client.post(reverse("player-activation-complete"), {"code": raw_code}, format="json")
        self.assertEqual(repeated.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(repeated.data["error"]["code"], "device_activation_invalid")

        refresh = public_client.post(reverse("player-token-refresh"), {}, format="json")
        self.assertEqual(refresh.status_code, status.HTTP_200_OK, refresh.data)
        self.assertIn("bm_device_refresh", refresh.cookies)

    def test_device_access_cannot_be_used_as_user_token_and_user_token_cannot_be_used_by_player(self):
        device = Device.objects.get(id=self.create_device().data["id"])
        code = self.client.post(reverse("device-activation-code", kwargs={"device_id": device.id}), {}, format="json").data["code"]
        completed = APIClient().post(reverse("player-activation-complete"), {"code": code}, format="json")
        device_access = completed.data["device_access"]

        panel = APIClient()
        panel.credentials(HTTP_AUTHORIZATION=f"Bearer {device_access}")
        self.assertEqual(panel.get(reverse("device-list")).status_code, status.HTTP_401_UNAUTHORIZED)

        user_access = str(AccessToken.for_user(self.user))
        player = APIClient()
        player.credentials(HTTP_AUTHORIZATION=f"Bearer {user_access}")
        self.assertEqual(player.get(reverse("player-session")).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_revoked_device_cannot_refresh_and_logout_is_idempotent(self):
        device = Device.objects.get(id=self.create_device().data["id"])
        code = self.client.post(reverse("device-activation-code", kwargs={"device_id": device.id}), {}, format="json").data["code"]
        player = APIClient()
        complete = player.post(reverse("player-activation-complete"), {"code": code}, format="json")
        device.refresh_from_db()
        revoke = self.client.post(
            reverse("device-revoke", kwargs={"device_id": device.id}),
            {"expected_revision": device.configuration_version},
            format="json",
        )
        self.assertEqual(revoke.status_code, status.HTTP_200_OK, revoke.data)
        self.assertEqual(player.post(reverse("player-token-refresh"), {}, format="json").status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(player.post(reverse("player-logout"), {}, format="json").status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(player.post(reverse("player-logout"), {}, format="json").status_code, status.HTTP_204_NO_CONTENT)

    def test_scope_restricts_device_visibility(self):
        scoped_user = f.user("operator-devices@example.com")
        scoped_user.email_verified_at = timezone.now()
        scoped_user.save(update_fields=["email_verified_at"])
        scoped_membership = f.membership(self.company, scoped_user)
        self.create_device()
        second_zone = f.zone(self.company, self.site, "scope-zone")
        self.create_device(name="Fuera", code="OUTSIDE", zone_id=str(second_zone.id))
        self.membership = scoped_membership
        self.user = scoped_user
        self.grant_permissions("devices.view", scope=get_or_create_zone_scope(zone=self.zone))
        self.client.force_authenticate(scoped_user)

        response = self.client.get(reverse("device-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)

    def test_expired_activation_code_is_rejected(self):
        device = Device.objects.get(id=self.create_device().data["id"])
        code = self.client.post(reverse("device-activation-code", kwargs={"device_id": device.id}), {}, format="json").data["code"]
        DeviceActivation.objects.filter(device=device).update(expires_at=timezone.now() - timedelta(seconds=1))

        response = APIClient().post(reverse("player-activation-validate"), {"code": code}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_new_activation_code_revokes_the_previous_code(self):
        device = Device.objects.get(id=self.create_device().data["id"])
        first = self.client.post(reverse("device-activation-code", kwargs={"device_id": device.id}), {}, format="json").data["code"]
        second = self.client.post(reverse("device-activation-code", kwargs={"device_id": device.id}), {}, format="json").data["code"]

        self.assertNotEqual(first, second)
        self.assertEqual(APIClient().post(reverse("player-activation-validate"), {"code": first}, format="json").status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(APIClient().post(reverse("player-activation-validate"), {"code": second}, format="json").status_code, status.HTTP_200_OK)

    def test_trial_expired_blocks_device_mutations(self):
        subscription = f.subscription(self.company)
        subscription.status = subscription.Status.TRIAL
        subscription.trial_ends_at = timezone.now() - timedelta(seconds=1)
        subscription.save(update_fields=["status", "trial_ends_at"])

        response = self.client.post(
            reverse("device-list"),
            {"name": "No permitido", "code": "BLOCKED", "zone_id": str(self.zone.id)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["error"]["code"], "functional_access_blocked")

    def test_command_is_idempotent_and_volume_is_validated(self):
        device = Device.objects.get(id=self.create_device().data["id"])
        payload = {"command_type": "SET_VOLUME", "payload": {"volume": 55}, "idempotency_key": "00000000-0000-0000-0000-000000000123"}
        first = self.client.post(reverse("device-command-create", kwargs={"device_id": device.id}), payload, format="json")
        second = self.client.post(reverse("device-command-create", kwargs={"device_id": device.id}), payload, format="json")
        invalid = self.client.post(
            reverse("device-command-create", kwargs={"device_id": device.id}),
            {"command_type": "SET_VOLUME", "payload": {"volume": 101}},
            format="json",
        )

        self.assertEqual(first.status_code, status.HTTP_201_CREATED, first.data)
        self.assertEqual(second.status_code, status.HTTP_201_CREATED, second.data)
        self.assertEqual(first.data["id"], second.data["id"])
        self.assertEqual(invalid.status_code, status.HTTP_400_BAD_REQUEST)

    @override_settings(BM_GO_SERVICE_TOKEN="service-token")
    def test_introspection_requires_service_token(self):
        device = Device.objects.get(id=self.create_device().data["id"])
        code = self.client.post(reverse("device-activation-code", kwargs={"device_id": device.id}), {}, format="json").data["code"]
        access = APIClient().post(reverse("player-activation-complete"), {"code": code}, format="json").data["device_access"]
        internal = APIClient()

        self.assertEqual(internal.post(reverse("player-token-introspect"), {"token": access}, format="json").status_code, status.HTTP_403_FORBIDDEN)
        response = internal.post(
            reverse("player-token-introspect"),
            {"token": access},
            format="json",
            HTTP_X_BRANDYMANAGER_SERVICE_TOKEN="service-token",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["device_id"], str(device.id))

    @override_settings(BM_DEVICE_ACTIVATION_RATE_LIMIT_ATTEMPTS=1, BM_DEVICE_ACTIVATION_RATE_LIMIT_WINDOW=300)
    def test_activation_attempts_are_rate_limited_by_ip(self):
        client = APIClient()
        first = client.post(
            reverse("player-activation-validate"),
            {"code": "AAAA-BBBB-CCCC"},
            format="json",
            REMOTE_ADDR="203.0.113.77",
        )
        second = client.post(
            reverse("player-activation-validate"),
            {"code": "AAAA-BBBB-CCCC"},
            format="json",
            REMOTE_ADDR="203.0.113.77",
        )

        self.assertEqual(first.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(second.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
