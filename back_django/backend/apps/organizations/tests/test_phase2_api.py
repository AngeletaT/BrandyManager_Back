from datetime import timedelta

from django.core import mail
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.authorization.models import CompanyRole, PlatformRole, UserPlatformRole
from apps.billing.models import Plan, Subscription
from apps.billing.services import create_trial_subscription
from apps.organizations.models import Company, CompanyInvitation, CompanyMembership, MembershipGrant, ResourceScope, Site, Zone
from apps.organizations.tests import factories as f
from apps.users.services import hash_action_token


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", FRONTEND_BASE_URL="http://localhost:5173")
class Phase2OrganizationAPITests(APITestCase):
    def setUp(self):
        call_command("seed_initial_data", verbosity=0)
        self.company = f.company("phase2")
        self.owner_user = self.verified_user("owner@example.com")
        self.owner_membership = self.add_member(self.owner_user, "OWNER")
        create_trial_subscription(company=self.company)

    def verified_user(self, email):
        return f.User.objects.create_user(
            email=email,
            password="StrongPass123!",
            first_name="Test",
            last_name="User",
            email_verified_at=timezone.now(),
        )

    def company_scope(self, company=None):
        scope, _ = ResourceScope.objects.get_or_create(
            company=company or self.company,
            scope_type=ResourceScope.ScopeType.COMPANY,
            defaults={"name": "Empresa", "is_system_generated": True},
        )
        return scope

    def site_scope(self, site):
        scope, _ = ResourceScope.objects.get_or_create(
            company=site.company,
            scope_type=ResourceScope.ScopeType.SITE,
            site=site,
            defaults={"name": site.name, "is_system_generated": True},
        )
        return scope

    def zone_scope(self, zone):
        scope, _ = ResourceScope.objects.get_or_create(
            company=zone.company,
            scope_type=ResourceScope.ScopeType.ZONE,
            zone=zone,
            defaults={"name": zone.name, "is_system_generated": True},
        )
        return scope

    def add_member(self, user, role_code, company=None, scope=None, status_value=CompanyMembership.Status.ACTIVE):
        company = company or self.company
        membership = CompanyMembership.objects.create(company=company, user=user, status=status_value, accepted_at=timezone.now())
        role = CompanyRole.objects.get(company=None, code=role_code)
        MembershipGrant.objects.create(membership=membership, role=role, scope=scope or self.company_scope(company))
        return membership

    def authenticate(self, user=None):
        self.client.force_authenticate(user=user or self.owner_user)

    def extract_invitation_token_from_last_email(self):
        return mail.outbox[-1].body.split("token=", 1)[1].split()[0]

    def post_invitation(self, payload):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(reverse("organization-invitation-create"), payload, format="json")

    def resend_invitation(self, invitation):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(reverse("organization-invitation-resend", kwargs={"invitation_id": invitation.id}))

    def site_payload(self, **overrides):
        payload = {
            "name": "Madrid Centro",
            "site_type": "BRANCH",
            "address_line_1": "Gran Via 1",
            "postal_code": "28013",
            "city": "Madrid",
            "timezone": "Europe/Madrid",
            "contact_name": "Ana",
            "contact_email": "ana@example.com",
            "contact_phone": "+34910000000",
        }
        payload.update(overrides)
        return payload

    def zone_payload(self, site, **overrides):
        payload = {
            "site_id": str(site.id),
            "name": "Sala principal",
            "description": "Zona de tienda",
        }
        payload.update(overrides)
        return payload

    def test_owner_can_view_update_company_and_create_site_zone(self):
        self.authenticate()

        company_response = self.client.get(reverse("organization-company"))
        update_response = self.client.patch(reverse("organization-company"), {"trade_name": "Phase 2 Retail"}, format="json")
        site_response = self.client.post(reverse("organization-site-list"), self.site_payload(), format="json")
        zone_response = self.client.post(reverse("organization-zone-list"), self.zone_payload(Site.objects.get()), format="json")

        self.assertEqual(company_response.status_code, status.HTTP_200_OK)
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)
        self.assertEqual(update_response.data["trade_name"], "Phase 2 Retail")
        self.assertEqual(site_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(zone_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(ResourceScope.objects.filter(scope_type=ResourceScope.ScopeType.SITE).count(), 1)
        self.assertEqual(ResourceScope.objects.filter(scope_type=ResourceScope.ScopeType.ZONE).count(), 1)

    def test_site_create_rejects_company_id_and_does_not_create_second_company(self):
        other_company = f.company("payload-company")
        self.authenticate()

        response = self.client.post(
            reverse("organization-site-list"),
            self.site_payload(company_id=str(other_company.id), company=str(other_company.id)),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("company_id", response.data["error"]["fields"])
        self.assertEqual(Company.objects.count(), 2)
        self.assertEqual(Site.objects.count(), 0)

    def test_site_list_supports_search_filters_and_pagination(self):
        Site.objects.create(
            company=self.company,
            name="Mercadona Valencia",
            code="VALENCIA-01",
            site_type=Site.SiteType.BRANCH,
            address_line_1="Calle Colon 1",
            postal_code="46001",
            city="Valencia",
            province="Valencia",
            country_code="ES",
            timezone="Europe/Madrid",
        )
        Site.objects.create(
            company=self.company,
            name="Franquicia Madrid Centro",
            code="MADRID-01",
            site_type=Site.SiteType.FRANCHISE,
            status=Site.Status.INACTIVE,
            address_line_1="Gran Via 1",
            postal_code="28013",
            city="Madrid",
            province="Madrid",
            country_code="ES",
            timezone="Europe/Madrid",
        )
        self.authenticate()

        response = self.client.get(
            reverse("organization-site-list"),
            {"search": "valencia", "status": "ACTIVE", "site_type": "BRANCH", "page": 1, "page_size": 1},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["page"], 1)
        self.assertEqual(response.data["page_size"], 1)
        self.assertEqual(response.data["results"][0]["name"], "Mercadona Valencia")
        self.assertEqual(response.data["results"][0]["site_type"], "BRANCH")

    def test_site_response_contract_includes_counts_and_permissions(self):
        site = f.site(self.company, "contract")
        f.zone(self.company, site, "contract-zone")
        Zone.objects.create(company=self.company, site=site, name="Archived", code="ARCH", status=Zone.Status.ARCHIVED)
        self.authenticate()

        response = self.client.get(reverse("organization-site-detail", kwargs={"site_id": site.id}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["zone_count"], 1)
        self.assertEqual(response.data["permissions"], {"can_view": True, "can_update": True, "can_archive": True})
        self.assertNotIn("company", response.data)
        self.assertNotIn("metadata", response.data)

    def test_manager_can_create_update_archive_and_reactivate_site(self):
        manager = self.verified_user("manager-sites@example.com")
        self.add_member(manager, "MANAGER")
        self.authenticate(manager)

        create_response = self.client.post(reverse("organization-site-list"), self.site_payload(code="CASTELLON-01", site_type="STORE"), format="json")
        site_id = create_response.data["id"]
        update_response = self.client.patch(reverse("organization-site-detail", kwargs={"site_id": site_id}), {"name": "Mercadona Castellon", "site_type": "BRANCH"}, format="json")
        archive_response = self.client.post(reverse("organization-site-archive", kwargs={"site_id": site_id}))
        reactivate_response = self.client.post(reverse("organization-site-reactivate", kwargs={"site_id": site_id}))

        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(create_response.data["site_type"], "STORE")
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)
        self.assertEqual(update_response.data["site_type"], "BRANCH")
        self.assertEqual(archive_response.status_code, status.HTTP_200_OK)
        self.assertEqual(archive_response.data["status"], "ARCHIVED")
        self.assertEqual(reactivate_response.status_code, status.HTTP_200_OK)
        self.assertEqual(reactivate_response.data["status"], "ACTIVE")

    def test_site_archive_archives_child_zones_without_destroying_scope(self):
        site = f.site(self.company, "site-with-zones")
        zone = f.zone(self.company, site, "zone-to-archive")
        site_scope = self.site_scope(site)
        self.authenticate()

        response = self.client.post(reverse("organization-site-archive", kwargs={"site_id": site.id}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        site.refresh_from_db()
        zone.refresh_from_db()
        self.assertEqual(site.status, Site.Status.ARCHIVED)
        self.assertEqual(zone.status, Zone.Status.ARCHIVED)
        self.assertTrue(ResourceScope.objects.filter(id=site_scope.id).exists())

    def test_archived_site_cannot_be_updated_and_reactivate_checks_site_limit(self):
        subscription = self.company.subscriptions.get()
        subscription.plan_snapshot["limits"]["sites"] = 1
        subscription.save(update_fields=["plan_snapshot"])
        archived_site = f.site(self.company, "archived-reactivate")
        archived_site.status = Site.Status.ARCHIVED
        archived_site.archived_at = timezone.now()
        archived_site.save(update_fields=["status", "archived_at", "updated_at"])
        f.site(self.company, "active-limit")
        self.authenticate()

        patch_response = self.client.patch(
            reverse("organization-site-detail", kwargs={"site_id": archived_site.id}),
            {"contact_phone": "+34911111111"},
            format="json",
        )
        reactivate_response = self.client.post(reverse("organization-site-reactivate", kwargs={"site_id": archived_site.id}))

        self.assertEqual(patch_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(reactivate_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(reactivate_response.data["error"]["code"], "plan_limit_reached")

    def test_viewer_cannot_update_archive_or_reactivate_site(self):
        site = f.site(self.company, "viewer-site")
        viewer = self.verified_user("viewer-sites@example.com")
        self.add_member(viewer, "VIEWER")
        self.authenticate(viewer)

        patch_response = self.client.patch(reverse("organization-site-detail", kwargs={"site_id": site.id}), {"name": "No"}, format="json")
        archive_response = self.client.post(reverse("organization-site-archive", kwargs={"site_id": site.id}))
        reactivate_response = self.client.post(reverse("organization-site-reactivate", kwargs={"site_id": site.id}))

        self.assertEqual(patch_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(archive_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(reactivate_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_operator_cannot_update_site_outside_scope(self):
        assigned = f.site(self.company, "assigned")
        outside = f.site(self.company, "outside")
        operator = self.verified_user("operator-wrong-scope@example.com")
        membership = CompanyMembership.objects.create(company=self.company, user=operator, status=CompanyMembership.Status.ACTIVE)
        role = CompanyRole.objects.get(company=None, code="OPERADOR_SEDES")
        MembershipGrant.objects.create(membership=membership, role=role, scope=self.site_scope(assigned))
        self.authenticate(operator)

        response = self.client.patch(
            reverse("organization-site-detail", kwargs={"site_id": outside.id}),
            {"contact_phone": "+34922222222"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["error"]["code"], "site_not_found")

    def test_site_code_is_unique_per_company(self):
        f.site(self.company, "DUPLICATED")
        self.authenticate()

        response = self.client.post(reverse("organization-site-list"), self.site_payload(code="DUPLICATED"), format="json")

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["error"]["code"], "site_code_conflict")

    def test_zone_response_contract_includes_site_summary_and_permissions(self):
        site = f.site(self.company, "zone-contract-site")
        zone = f.zone(self.company, site, "zone-contract")
        self.authenticate()

        response = self.client.get(reverse("organization-zone-detail", kwargs={"zone_id": zone.id}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["site"], {"id": str(site.id), "name": site.name})
        self.assertEqual(response.data["permissions"], {"can_view": True, "can_update": True, "can_archive": True})
        self.assertNotIn("company", response.data)
        self.assertNotIn("metadata", response.data)
        self.assertNotIn("channel_id", response.data)
        self.assertNotIn("device_id", response.data)

    def test_zone_list_supports_site_filter_search_status_and_pagination(self):
        site_a = f.site(self.company, "valencia-site")
        site_b = f.site(self.company, "castellon-site")
        f.zone(self.company, site_a, "CAJAS")
        Zone.objects.create(company=self.company, site=site_a, name="Panaderia", code="PAN", status=Zone.Status.INACTIVE)
        f.zone(self.company, site_b, "PARKING")
        self.authenticate()

        response = self.client.get(
            reverse("organization-zone-list"),
            {"site_id": str(site_a.id), "search": "cajas", "status": "ACTIVE", "page": 1, "page_size": 1},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["page"], 1)
        self.assertEqual(response.data["page_size"], 1)
        self.assertEqual(response.data["results"][0]["name"], "CAJAS")

    def test_manager_can_create_update_archive_and_reactivate_zone(self):
        site = f.site(self.company, "manager-zone-site")
        manager = self.verified_user("manager-zones@example.com")
        self.add_member(manager, "MANAGER")
        self.authenticate(manager)

        create_response = self.client.post(
            reverse("organization-zone-list"),
            self.zone_payload(site, code="CAJAS", timezone="Europe/Madrid"),
            format="json",
        )
        zone_id = create_response.data["id"]
        update_response = self.client.patch(
            reverse("organization-zone-detail", kwargs={"zone_id": zone_id}),
            {"name": "Zona de cajas", "code": "CAJAS-01", "timezone": ""},
            format="json",
        )
        archive_response = self.client.post(reverse("organization-zone-archive", kwargs={"zone_id": zone_id}))
        reactivate_response = self.client.post(reverse("organization-zone-reactivate", kwargs={"zone_id": zone_id}))

        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(create_response.data["code"], "CAJAS")
        self.assertEqual(create_response.data["timezone"], "Europe/Madrid")
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)
        self.assertEqual(update_response.data["name"], "Zona de cajas")
        self.assertEqual(update_response.data["code"], "CAJAS-01")
        self.assertIsNone(update_response.data["timezone"])
        self.assertEqual(archive_response.status_code, status.HTTP_200_OK)
        self.assertEqual(archive_response.data["status"], Zone.Status.ARCHIVED)
        self.assertEqual(reactivate_response.status_code, status.HTTP_200_OK)
        self.assertEqual(reactivate_response.data["status"], Zone.Status.ACTIVE)

    def test_zone_create_rejects_forbidden_payload_fields(self):
        site = f.site(self.company, "forbidden-zone-site")
        payload = self.zone_payload(
            site,
            company_id=str(self.company.id),
            status=Zone.Status.SUSPENDED,
            metadata={"capacity": 50},
            channel_id="not-yet",
        )
        payload["site"] = str(site.id)
        self.authenticate()

        response = self.client.post(
            reverse("organization-zone-list"),
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("company_id", response.data["error"]["fields"])
        self.assertIn("metadata", response.data["error"]["fields"])
        self.assertEqual(Zone.objects.filter(site=site).count(), 0)

    def test_zone_create_requires_site_from_current_company_and_not_archived(self):
        other_company = f.company("other-zone-site")
        other_site = f.site(other_company, "other-zone-site")
        archived_site = f.site(self.company, "archived-zone-site")
        archived_site.status = Site.Status.ARCHIVED
        archived_site.archived_at = timezone.now()
        archived_site.save(update_fields=["status", "archived_at", "updated_at"])
        self.authenticate()

        other_response = self.client.post(reverse("organization-zone-list"), self.zone_payload(other_site), format="json")
        archived_response = self.client.post(reverse("organization-zone-list"), self.zone_payload(archived_site), format="json")

        self.assertEqual(other_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(other_response.data["error"]["code"], "site_not_found")
        self.assertEqual(archived_response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(archived_response.data["error"]["code"], "site_archived")

    def test_zone_code_is_unique_within_site(self):
        site = f.site(self.company, "duplicate-zone-site")
        f.zone(self.company, site, "DUP-ZONE")
        self.authenticate()

        response = self.client.post(reverse("organization-zone-list"), self.zone_payload(site, code="DUP-ZONE"), format="json")

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["error"]["code"], "zone_code_conflict")

    def test_zone_update_does_not_allow_moving_between_sites(self):
        site = f.site(self.company, "zone-move-source")
        target_site = f.site(self.company, "zone-move-target")
        zone = f.zone(self.company, site, "zone-move")
        self.authenticate()

        response = self.client.patch(
            reverse("organization-zone-detail", kwargs={"zone_id": zone.id}),
            {"site_id": str(target_site.id)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("site_id", response.data["error"]["fields"])
        zone.refresh_from_db()
        self.assertEqual(zone.site_id, site.id)

    def test_zone_scope_is_created_automatically(self):
        site = f.site(self.company, "auto-zone-scope-site")
        self.authenticate()

        response = self.client.post(reverse("organization-zone-list"), self.zone_payload(site, code="AUTO-SCOPE"), format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(ResourceScope.objects.filter(scope_type=ResourceScope.ScopeType.ZONE, zone_id=response.data["id"]).exists())

    def test_company_response_includes_permissions_usage_settings_and_limits(self):
        f.site(self.company, "usage-a")
        site = f.site(self.company, "usage-b")
        f.zone(self.company, site, "usage-zone")
        self.authenticate()

        response = self.client.get(reverse("organization-company"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["settings"], self.company.settings)
        self.assertTrue(response.data["permissions"]["can_update"])
        self.assertEqual(response.data["usage"]["sites"], {"used": 2, "limit": 10})
        self.assertEqual(response.data["usage"]["zones"], {"used": 1, "limit": 30})
        self.assertEqual(response.data["usage"]["users"], {"used": 1, "limit": 10})

    def test_manager_can_view_and_update_company(self):
        manager = self.verified_user("manager-company@example.com")
        self.add_member(manager, "MANAGER")
        self.authenticate(manager)

        view_response = self.client.get(reverse("organization-company"))
        patch_response = self.client.patch(
            reverse("organization-company"),
            {
                "legal_name": "  Mercadona S.A.  ",
                "trade_name": " Mercadona ",
                "tax_id": " a00000000 ",
                "billing_email": "facturacion@mercadona.es",
                "contact_email": "contacto@mercadona.es",
                "phone": "+34960000000",
                "country_code": "es",
                "default_timezone": "Europe/Madrid",
                "default_language": "ES",
                "sector": "retail",
            },
            format="json",
        )

        self.assertEqual(view_response.status_code, status.HTTP_200_OK)
        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)
        self.assertEqual(patch_response.data["legal_name"], "Mercadona S.A.")
        self.assertEqual(patch_response.data["trade_name"], "Mercadona")
        self.assertEqual(patch_response.data["tax_id"], "A00000000")
        self.assertEqual(patch_response.data["country_code"], "ES")
        self.assertEqual(patch_response.data["default_language"], "es")
        self.assertEqual(patch_response.data["sector"], "retail")

    def test_read_roles_can_view_company_but_cannot_update(self):
        viewer = self.verified_user("viewer-company@example.com")
        self.add_member(viewer, "VIEWER")
        self.authenticate(viewer)

        view_response = self.client.get(reverse("organization-company"))
        patch_response = self.client.patch(reverse("organization-company"), {"trade_name": "Nope"}, format="json")

        self.assertEqual(view_response.status_code, status.HTTP_200_OK)
        self.assertFalse(view_response.data["permissions"]["can_update"])
        self.assertEqual(patch_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(patch_response.data["error"]["code"], "permission_denied")

    def test_company_endpoint_rejects_user_without_active_membership(self):
        pending_user = self.verified_user("pending-company@example.com")
        suspended_user = self.verified_user("suspended-company@example.com")
        self.add_member(suspended_user, "VIEWER", status_value=CompanyMembership.Status.SUSPENDED)

        self.authenticate(pending_user)
        no_membership_response = self.client.get(reverse("organization-company"))
        self.authenticate(suspended_user)
        suspended_response = self.client.get(reverse("organization-company"))

        self.assertEqual(no_membership_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(no_membership_response.data["error"]["code"], "company_access_denied")
        self.assertEqual(suspended_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(suspended_response.data["error"]["code"], "company_access_denied")

    def test_company_update_rejects_forbidden_payload_fields(self):
        self.authenticate()

        response = self.client.patch(
            reverse("organization-company"),
            {
                "status": "ACTIVE",
                "plan": "PREMIUM",
                "role": "OWNER",
                "is_staff": True,
                "platform_roles": ["SUPERADMIN"],
                "settings": {"anything": True},
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("status", response.data["error"]["fields"])
        self.assertIn("is_staff", response.data["error"]["fields"])
        self.company.refresh_from_db()
        self.assertEqual(self.company.status, self.company.Status.TRIAL)

    def test_company_update_rejects_duplicate_tax_id_with_conflict(self):
        f.company("duplicate-tax")
        duplicated = Company.objects.get(trade_name="duplicate-tax").tax_id
        self.authenticate()

        response = self.client.patch(reverse("organization-company"), {"tax_id": duplicated.lower()}, format="json")

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["error"]["code"], "company_tax_id_already_registered")

    def test_expired_trial_allows_company_read_but_blocks_company_update(self):
        subscription = self.company.subscriptions.get()
        subscription.trial_ends_at = timezone.now() - timedelta(days=1)
        subscription.current_period_end = subscription.trial_ends_at
        subscription.save(update_fields=["trial_ends_at", "current_period_end"])
        self.authenticate()

        read_response = self.client.get(reverse("organization-company"))
        patch_response = self.client.patch(reverse("organization-company"), {"trade_name": "Expired"}, format="json")

        self.assertEqual(read_response.status_code, status.HTTP_200_OK)
        self.assertEqual(patch_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(patch_response.data["error"]["code"], "functional_access_blocked")
        self.assertEqual(patch_response.data["error"]["block_reason"], "trial_expired")

    def test_company_endpoint_does_not_create_or_delete_company(self):
        self.authenticate()

        post_response = self.client.post(reverse("organization-company"), {"trade_name": "Second"}, format="json")
        delete_response = self.client.delete(reverse("organization-company"))

        self.assertEqual(post_response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(delete_response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(Company.objects.count(), 1)

    def test_viewer_can_read_but_cannot_create_site(self):
        viewer = self.verified_user("viewer@example.com")
        self.add_member(viewer, "VIEWER")
        self.authenticate(viewer)

        list_response = self.client.get(reverse("organization-site-list"))
        create_response = self.client.post(reverse("organization-site-list"), self.site_payload(), format="json")

        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(create_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(create_response.data["error"]["code"], "permission_denied")

    def test_operator_with_multiple_site_scopes_sees_only_assigned_sites_and_zones(self):
        site_a = f.site(self.company, "a")
        site_b = f.site(self.company, "b")
        site_c = f.site(self.company, "c")
        zone_a = f.zone(self.company, site_a, "za")
        zone_b = f.zone(self.company, site_b, "zb")
        zone_c = f.zone(self.company, site_c, "zc")
        operator = self.verified_user("operator@example.com")
        membership = CompanyMembership.objects.create(company=self.company, user=operator, status=CompanyMembership.Status.ACTIVE)
        role = CompanyRole.objects.get(company=None, code="OPERADOR_SEDES")
        MembershipGrant.objects.create(membership=membership, role=role, scope=self.site_scope(site_a))
        MembershipGrant.objects.create(membership=membership, role=role, scope=self.site_scope(site_b))
        self.authenticate(operator)

        sites_response = self.client.get(reverse("organization-site-list"))
        zones_response = self.client.get(reverse("organization-zone-list"))
        company_response = self.client.get(reverse("organization-company"))

        self.assertEqual(company_response.status_code, status.HTTP_200_OK)
        self.assertEqual({row["id"] for row in sites_response.data["results"]}, {str(site_a.id), str(site_b.id)})
        self.assertEqual({row["id"] for row in zones_response.data["results"]}, {str(zone_a.id), str(zone_b.id)})
        self.assertNotIn(str(site_c.id), {row["id"] for row in sites_response.data["results"]})
        self.assertNotIn(str(zone_c.id), {row["id"] for row in zones_response.data["results"]})

    def test_operator_can_update_only_operational_fields_in_assigned_scope(self):
        site = f.site(self.company, "operational")
        operator = self.verified_user("operator-update@example.com")
        membership = CompanyMembership.objects.create(company=self.company, user=operator, status=CompanyMembership.Status.ACTIVE)
        role = CompanyRole.objects.get(company=None, code="OPERADOR_SEDES")
        MembershipGrant.objects.create(membership=membership, role=role, scope=self.site_scope(site))
        self.authenticate(operator)

        operational_response = self.client.patch(
            reverse("organization-site-detail", kwargs={"site_id": site.id}),
            {"contact_name": "Contacto", "contact_email": "contacto-sede@example.com", "contact_phone": "+34911111111"},
            format="json",
        )
        rename_response = self.client.patch(
            reverse("organization-site-detail", kwargs={"site_id": site.id}),
            {"name": "Nuevo nombre"},
            format="json",
        )
        archive_response = self.client.post(reverse("organization-site-archive", kwargs={"site_id": site.id}))

        self.assertEqual(operational_response.status_code, status.HTTP_200_OK)
        self.assertEqual(operational_response.data["contact_name"], "Contacto")
        self.assertEqual(operational_response.data["contact_email"], "contacto-sede@example.com")
        self.assertEqual(operational_response.data["contact_phone"], "+34911111111")
        self.assertEqual(rename_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(archive_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_operator_can_update_zone_operational_fields_from_site_scope(self):
        site = f.site(self.company, "operator-zone-site")
        zone = f.zone(self.company, site, "operator-zone")
        operator = self.verified_user("operator-zone-update@example.com")
        membership = CompanyMembership.objects.create(company=self.company, user=operator, status=CompanyMembership.Status.ACTIVE)
        role = CompanyRole.objects.get(company=None, code="OPERADOR_SEDES")
        MembershipGrant.objects.create(membership=membership, role=role, scope=self.site_scope(site))
        self.authenticate(operator)

        operational_response = self.client.patch(
            reverse("organization-zone-detail", kwargs={"zone_id": zone.id}),
            {"description": "Zona de cajas operativa", "timezone": "Europe/Madrid"},
            format="json",
        )
        structural_response = self.client.patch(
            reverse("organization-zone-detail", kwargs={"zone_id": zone.id}),
            {"name": "Nombre no permitido"},
            format="json",
        )
        archive_response = self.client.post(reverse("organization-zone-archive", kwargs={"zone_id": zone.id}))

        self.assertEqual(operational_response.status_code, status.HTTP_200_OK)
        self.assertEqual(operational_response.data["description"], "Zona de cajas operativa")
        self.assertEqual(operational_response.data["timezone"], "Europe/Madrid")
        self.assertEqual(structural_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(archive_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_operator_with_zone_scope_cannot_access_other_zone(self):
        site = f.site(self.company, "operator-zone-scope-site")
        assigned_zone = f.zone(self.company, site, "assigned-zone")
        outside_zone = f.zone(self.company, site, "outside-zone")
        operator = self.verified_user("operator-zone-scope@example.com")
        membership = CompanyMembership.objects.create(company=self.company, user=operator, status=CompanyMembership.Status.ACTIVE)
        role = CompanyRole.objects.get(company=None, code="OPERADOR_SEDES")
        MembershipGrant.objects.create(membership=membership, role=role, scope=self.zone_scope(assigned_zone))
        self.authenticate(operator)

        assigned_response = self.client.get(reverse("organization-zone-detail", kwargs={"zone_id": assigned_zone.id}))
        outside_response = self.client.get(reverse("organization-zone-detail", kwargs={"zone_id": outside_zone.id}))

        self.assertEqual(assigned_response.status_code, status.HTTP_200_OK)
        self.assertEqual(outside_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(outside_response.data["error"]["code"], "zone_not_found")

    def test_viewer_can_read_but_cannot_mutate_zone(self):
        site = f.site(self.company, "viewer-zone-site")
        zone = f.zone(self.company, site, "viewer-zone")
        viewer = self.verified_user("viewer-zone@example.com")
        self.add_member(viewer, "VIEWER")
        self.authenticate(viewer)

        list_response = self.client.get(reverse("organization-zone-list"))
        create_response = self.client.post(reverse("organization-zone-list"), self.zone_payload(site), format="json")
        patch_response = self.client.patch(reverse("organization-zone-detail", kwargs={"zone_id": zone.id}), {"description": "No"}, format="json")
        archive_response = self.client.post(reverse("organization-zone-archive", kwargs={"zone_id": zone.id}))
        reactivate_response = self.client.post(reverse("organization-zone-reactivate", kwargs={"zone_id": zone.id}))

        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(create_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(patch_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(archive_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(reactivate_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_isolation_between_companies_blocks_cross_company_site(self):
        other_company = f.company("other-phase2")
        other_user = self.verified_user("other@example.com")
        self.add_member(other_user, "OWNER", company=other_company, scope=self.company_scope(other_company))
        create_trial_subscription(company=other_company)
        site = f.site(self.company, "isolated")
        self.authenticate(other_user)

        response = self.client.get(reverse("organization-site-detail", kwargs={"site_id": site.id}))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["error"]["code"], "site_not_found")

    def test_isolation_between_companies_blocks_cross_company_zone(self):
        other_company = f.company("other-zone-phase2")
        other_user = self.verified_user("other-zone@example.com")
        self.add_member(other_user, "OWNER", company=other_company, scope=self.company_scope(other_company))
        create_trial_subscription(company=other_company)
        site = f.site(self.company, "isolated-zone-site")
        zone = f.zone(self.company, site, "isolated-zone")
        self.authenticate(other_user)

        response = self.client.get(reverse("organization-zone-detail", kwargs={"zone_id": zone.id}))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["error"]["code"], "zone_not_found")

    def test_site_and_zone_limits_are_enforced(self):
        subscription = self.company.subscriptions.get()
        subscription.plan_snapshot["limits"]["sites"] = 1
        subscription.plan_snapshot["limits"]["zones"] = 1
        subscription.save(update_fields=["plan_snapshot"])
        f.site(self.company, "existing")
        self.authenticate()

        site_response = self.client.post(reverse("organization-site-list"), self.site_payload(name="Second"), format="json")

        self.assertEqual(site_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(site_response.data["error"]["code"], "plan_limit_reached")

        subscription.plan_snapshot["limits"]["sites"] = 2
        subscription.save(update_fields=["plan_snapshot"])
        site = f.site(self.company, "zone-limit")
        f.zone(self.company, site, "existing-zone")
        zone_response = self.client.post(reverse("organization-zone-list"), self.zone_payload(site, name="Second zone"), format="json")

        self.assertEqual(zone_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(zone_response.data["error"]["fields"]["zones"], ["Limite alcanzado."])

    def test_zone_reactivation_checks_limit_and_archived_site(self):
        site = f.site(self.company, "zone-reactivation-site")
        archived_zone = f.zone(self.company, site, "archived-zone")
        archived_zone.status = Zone.Status.ARCHIVED
        archived_zone.archived_at = timezone.now()
        archived_zone.save(update_fields=["status", "archived_at", "updated_at"])
        f.zone(self.company, site, "active-zone")
        subscription = self.company.subscriptions.get()
        subscription.plan_snapshot["limits"]["zones"] = 1
        subscription.save(update_fields=["plan_snapshot"])
        self.authenticate()

        limit_response = self.client.post(reverse("organization-zone-reactivate", kwargs={"zone_id": archived_zone.id}))

        self.assertEqual(limit_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(limit_response.data["error"]["code"], "plan_limit_reached")

        active_zone = Zone.objects.get(code="active-zone")
        active_zone.status = Zone.Status.ARCHIVED
        active_zone.archived_at = timezone.now()
        active_zone.save(update_fields=["status", "archived_at", "updated_at"])
        site.status = Site.Status.ARCHIVED
        site.archived_at = timezone.now()
        site.save(update_fields=["status", "archived_at", "updated_at"])
        archived_site_response = self.client.post(reverse("organization-zone-reactivate", kwargs={"zone_id": archived_zone.id}))

        self.assertEqual(archived_site_response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(archived_site_response.data["error"]["code"], "site_archived")

    def test_expired_trial_blocks_functional_endpoints(self):
        subscription = self.company.subscriptions.get()
        subscription.trial_ends_at = timezone.now() - timedelta(days=1)
        subscription.current_period_end = subscription.trial_ends_at
        subscription.save(update_fields=["trial_ends_at", "current_period_end"])
        self.authenticate()

        site_response = self.client.get(reverse("organization-site-list"))
        zone_response = self.client.get(reverse("organization-zone-list"))

        self.assertEqual(site_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(site_response.data["error"]["code"], "functional_access_blocked")
        self.assertEqual(site_response.data["error"]["block_reason"], "trial_expired")
        self.assertEqual(zone_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(zone_response.data["error"]["code"], "functional_access_blocked")
        self.assertEqual(zone_response.data["error"]["block_reason"], "trial_expired")

    def test_manager_cannot_suspend_owner_or_assign_owner(self):
        manager = self.verified_user("manager@example.com")
        self.add_member(manager, "MANAGER")
        worker = self.verified_user("worker@example.com")
        worker_membership = self.add_member(worker, "VIEWER")
        self.authenticate(manager)

        suspend_response = self.client.post(reverse("organization-membership-suspend", kwargs={"membership_id": self.owner_membership.id}))
        owner_role_response = self.client.patch(
            reverse("organization-membership-detail", kwargs={"membership_id": worker_membership.id}),
            {"role_code": "OWNER"},
            format="json",
        )

        self.assertEqual(suspend_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(suspend_response.data["error"]["code"], "protected_owner")
        self.assertEqual(owner_role_response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_owner_invites_worker_with_secure_token_and_email(self):
        self.authenticate()

        response = self.post_invitation(
            {
                "email": "new-worker@example.com",
                "first_name": "New",
                "last_name": "Worker",
                "role_code": "VIEWER",
                "is_staff": True,
                "is_superuser": True,
                "platform_role": "SUPERADMIN",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        invitation = CompanyInvitation.objects.get(invited_email="new-worker@example.com")
        raw_token = self.extract_invitation_token_from_last_email()
        self.assertEqual(response.data["status"], "PENDING")
        self.assertEqual(response.data["role"]["code"], "VIEWER")
        self.assertIn("http://localhost:5173/invitacion?token=", mail.outbox[0].body)
        self.assertEqual(invitation.token_hash, hash_action_token(raw_token=raw_token))
        self.assertFalse(CompanyInvitation.objects.filter(token_hash=raw_token).exists())
        self.assertFalse(CompanyMembership.objects.filter(user__email="new-worker@example.com").exists())

    def test_manager_can_invite_allowed_roles_but_not_owner(self):
        manager = self.verified_user("manager-invites@example.com")
        self.add_member(manager, "MANAGER")
        self.authenticate(manager)

        manager_invite = self.post_invitation({"email": "manager-worker@example.com", "role_code": "MANAGER"})
        owner_invite = self.client.post(
            reverse("organization-invitation-create"),
            {"email": "owner-worker@example.com", "role_code": "OWNER"},
            format="json",
        )

        self.assertEqual(manager_invite.status_code, status.HTTP_201_CREATED)
        self.assertEqual(owner_invite.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invitation_acceptance_for_new_user_creates_membership_without_company_or_trial(self):
        self.authenticate()
        self.post_invitation(
            {
                "email": "accepted-worker@example.com",
                "first_name": "Accepted",
                "last_name": "Worker",
                "role_code": "VIEWER",
            },
        )
        raw_token = self.extract_invitation_token_from_last_email()
        self.client.force_authenticate(user=None)

        validate_response = self.client.post(reverse("organization-invitation-validate"), {"token": raw_token}, format="json")
        accept_response = self.client.post(
            reverse("organization-invitation-accept"),
            {"token": raw_token, "password": "StrongPass123!", "password_confirmation": "StrongPass123!"},
            format="json",
        )

        self.assertEqual(validate_response.status_code, status.HTTP_200_OK)
        self.assertTrue(validate_response.data["valid"])
        self.assertTrue(validate_response.data["requires_password"])
        self.assertEqual(accept_response.status_code, status.HTTP_200_OK)
        membership = CompanyMembership.objects.get(user__email="accepted-worker@example.com")
        self.assertEqual(membership.status, CompanyMembership.Status.ACTIVE)
        self.assertEqual(membership.company, self.company)
        self.assertEqual(membership.grants.get().role.code, "VIEWER")
        self.assertIsNotNone(membership.user.email_verified_at)
        self.assertFalse(membership.user.is_staff)
        self.assertFalse(membership.user.is_superuser)
        self.assertFalse(membership.user.platform_roles.exists())
        self.assertEqual(Company.objects.count(), 1)
        self.assertEqual(Subscription.objects.count(), 1)

    def test_invitation_acceptance_for_existing_user_without_membership(self):
        existing = self.verified_user("existing-worker@example.com")
        self.authenticate()
        self.post_invitation({"email": existing.email, "role_code": "EDITOR_PLAYLISTS"})
        raw_token = self.extract_invitation_token_from_last_email()
        self.client.force_authenticate(user=None)

        response = self.client.post(reverse("organization-invitation-accept"), {"token": raw_token}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        membership = CompanyMembership.objects.get(user=existing)
        self.assertEqual(membership.status, CompanyMembership.Status.ACTIVE)
        self.assertEqual(membership.grants.get().role.code, "EDITOR_PLAYLISTS")

    def test_invitation_rejects_acceptance_for_user_in_other_company(self):
        other_company = f.company("invited-other-company")
        user = self.verified_user("already-member@example.com")
        self.add_member(user, "VIEWER", company=other_company, scope=self.company_scope(other_company))
        role = CompanyRole.objects.get(company=None, code="VIEWER")
        raw_token = "manual-invitation-token"
        CompanyInvitation.objects.create(
            company=self.company,
            invited_email=user.email,
            role=role,
            token_hash=hash_action_token(raw_token=raw_token),
            expires_at=timezone.now() + timedelta(days=7),
        )

        response = self.client.post(reverse("organization-invitation-accept"), {"token": raw_token}, format="json")

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["error"]["code"], "user_already_belongs_to_company")
        self.assertEqual(CompanyMembership.objects.filter(user=user).count(), 1)

    def test_invitation_token_expiry_single_use_and_cancel(self):
        self.authenticate()
        self.post_invitation({"email": "single-use@example.com", "role_code": "VIEWER"})
        raw_token = self.extract_invitation_token_from_last_email()
        invitation = CompanyInvitation.objects.get(invited_email="single-use@example.com")
        self.client.force_authenticate(user=None)

        first_accept = self.client.post(
            reverse("organization-invitation-accept"),
            {"token": raw_token, "password": "StrongPass123!", "password_confirmation": "StrongPass123!"},
            format="json",
        )
        reused = self.client.post(
            reverse("organization-invitation-accept"),
            {"token": raw_token, "password": "StrongPass123!", "password_confirmation": "StrongPass123!"},
            format="json",
        )

        self.assertEqual(first_accept.status_code, status.HTTP_200_OK)
        self.assertEqual(reused.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(reused.data["error"]["code"], "invitation_token_invalid")

        expired_raw = "expired-invitation-token"
        CompanyInvitation.objects.create(
            company=self.company,
            invited_email="expired-invite@example.com",
            role=invitation.role,
            token_hash=hash_action_token(raw_token=expired_raw),
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        expired_validate = self.client.post(reverse("organization-invitation-validate"), {"token": expired_raw}, format="json")
        self.assertFalse(expired_validate.data["valid"])

        self.authenticate()
        cancel_response = self.client.post(reverse("organization-invitation-cancel", kwargs={"invitation_id": invitation.id}))
        self.assertEqual(cancel_response.status_code, status.HTTP_409_CONFLICT)

    def test_invitation_cancel_blocks_acceptance(self):
        self.authenticate()
        self.post_invitation({"email": "cancelled-invite@example.com", "role_code": "VIEWER"})
        raw_token = self.extract_invitation_token_from_last_email()
        invitation = CompanyInvitation.objects.get(invited_email="cancelled-invite@example.com")

        cancel_response = self.client.post(reverse("organization-invitation-cancel", kwargs={"invitation_id": invitation.id}))
        self.client.force_authenticate(user=None)
        accept_response = self.client.post(
            reverse("organization-invitation-accept"),
            {"token": raw_token, "password": "StrongPass123!", "password_confirmation": "StrongPass123!"},
            format="json",
        )

        self.assertEqual(cancel_response.status_code, status.HTTP_200_OK)
        self.assertEqual(cancel_response.data["status"], "CANCELLED")
        self.assertEqual(accept_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(accept_response.data["error"]["code"], "invitation_token_invalid")

    def test_invitation_resend_invalidates_previous_token(self):
        self.authenticate()
        self.post_invitation({"email": "resend@example.com", "role_code": "VIEWER"})
        first_raw = self.extract_invitation_token_from_last_email()
        invitation = CompanyInvitation.objects.get(invited_email="resend@example.com")
        CompanyInvitation.objects.filter(pk=invitation.pk).update(last_sent_at=timezone.now() - timedelta(minutes=3))

        response = self.resend_invitation(invitation)
        second_raw = self.extract_invitation_token_from_last_email()
        self.client.force_authenticate(user=None)
        first_validate = self.client.post(reverse("organization-invitation-validate"), {"token": first_raw}, format="json")
        second_validate = self.client.post(reverse("organization-invitation-validate"), {"token": second_raw}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(first_validate.data["valid"])
        self.assertTrue(second_validate.data["valid"])

    def test_invitation_resend_rate_limit_does_not_send_new_email(self):
        self.authenticate()
        self.post_invitation({"email": "rate-limited@example.com", "role_code": "VIEWER"})
        invitation = CompanyInvitation.objects.get(invited_email="rate-limited@example.com")
        original_token_hash = invitation.token_hash

        response = self.resend_invitation(invitation)

        invitation.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(invitation.token_hash, original_token_hash)
        self.assertEqual(len(mail.outbox), 1)

    def test_user_limit_is_enforced_for_invitations(self):
        subscription = self.company.subscriptions.get()
        subscription.plan_snapshot["limits"]["users"] = 1
        subscription.save(update_fields=["plan_snapshot"])
        self.authenticate()

        response = self.client.post(
            reverse("organization-invitation-create"),
            {"email": "limit@example.com", "role_code": "VIEWER"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["error"]["code"], "plan_limit_reached")

    def test_pending_invitations_reserve_user_limit(self):
        subscription = self.company.subscriptions.get()
        subscription.plan_snapshot["limits"]["users"] = 2
        subscription.save(update_fields=["plan_snapshot"])
        self.authenticate()

        first = self.post_invitation({"email": "first-reserve@example.com", "role_code": "VIEWER"})
        second = self.client.post(reverse("organization-invitation-create"), {"email": "second-reserve@example.com", "role_code": "VIEWER"}, format="json")

        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(second.data["error"]["code"], "plan_limit_reached")

    def test_invitation_supports_multiple_scopes_and_rejects_other_company_scope(self):
        site_a = f.site(self.company, "invite-site-a")
        site_b = f.site(self.company, "invite-site-b")
        other_company = f.company("other-scope-company")
        other_site = f.site(other_company, "other-scope-site")
        self.authenticate()

        response = self.post_invitation(
            {
                "email": "operator-scoped@example.com",
                "role_code": "OPERADOR_SEDES",
                "site_ids": [str(site_a.id), str(site_b.id)],
            },
        )
        raw_token = self.extract_invitation_token_from_last_email()
        other_scope_response = self.client.post(
            reverse("organization-invitation-create"),
            {
                "email": "operator-other-scope@example.com",
                "role_code": "OPERADOR_SEDES",
                "site_ids": [str(other_site.id)],
            },
            format="json",
        )
        self.client.force_authenticate(user=None)
        accept_response = self.client.post(
            reverse("organization-invitation-accept"),
            {"token": raw_token, "password": "StrongPass123!", "password_confirmation": "StrongPass123!"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(other_scope_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(accept_response.status_code, status.HTTP_200_OK)
        membership = CompanyMembership.objects.get(user__email="operator-scoped@example.com")
        self.assertEqual(membership.grants.filter(is_active=True).count(), 2)

    def test_suspended_member_loses_access_with_existing_token_context(self):
        worker = self.verified_user("suspended-worker@example.com")
        worker_membership = self.add_member(worker, "VIEWER")
        self.authenticate()

        suspend_response = self.client.post(reverse("organization-member-suspend", kwargs={"membership_id": worker_membership.id}))
        self.authenticate(worker)
        access_response = self.client.get(reverse("organization-company"))

        self.assertEqual(suspend_response.status_code, status.HTTP_200_OK)
        self.assertEqual(access_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(access_response.data["error"]["code"], "company_access_denied")

    def test_internal_admin_cannot_use_client_phase2_endpoints(self):
        internal = self.verified_user("internal@example.com")
        platform_role = PlatformRole.objects.get(code="SUPPORT_AGENT")
        UserPlatformRole.objects.create(user=internal, role=platform_role)
        self.authenticate(internal)

        response = self.client.get(reverse("organization-company"))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["error"]["code"], "company_access_denied")
