from django.core.management import call_command
from django.test import TestCase

from apps.authorization.catalog import COMPANY_ROLE_DEFINITIONS, OFFICIAL_COMPANY_ROLE_CODES
from apps.authorization.models import CompanyRole, CompanyRolePermission


class SeedAuthorizationTests(TestCase):
    def test_official_company_roles_are_created_without_duplicates(self):
        call_command("seed_initial_data", verbosity=0)
        call_command("seed_initial_data", verbosity=0)

        for code in OFFICIAL_COMPANY_ROLE_CODES:
            self.assertEqual(CompanyRole.objects.filter(company=None, code=code).count(), 1)

    def test_official_company_role_codes_are_stable(self):
        self.assertEqual(
            OFFICIAL_COMPANY_ROLE_CODES,
            ("OWNER", "MANAGER", "EDITOR_PLAYLISTS", "OPERADOR_SEDES", "VIEWER"),
        )

    def test_official_role_permissions_are_seeded_from_central_catalog(self):
        call_command("seed_initial_data", verbosity=0)

        owner = CompanyRole.objects.get(company=None, code="OWNER")
        owner_permission_codes = set(
            CompanyRolePermission.objects.filter(role=owner).values_list("permission__code", flat=True)
        )

        self.assertTrue(set(COMPANY_ROLE_DEFINITIONS["OWNER"]["permissions"]).issubset(owner_permission_codes))
        self.assertNotIn("platform.companies.manage", owner_permission_codes)
