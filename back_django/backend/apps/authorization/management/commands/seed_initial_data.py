from django.core.management.base import BaseCommand

from apps.authorization.catalog import COMPANY_ROLE_DEFINITIONS, OFFICIAL_PERMISSIONS, PLATFORM_ROLE_DEFINITIONS
from apps.authorization.models import CompanyRole, CompanyRolePermission, Permission, PlatformRole, PlatformRolePermission
from apps.billing.plans import OFFICIAL_PLAN_DEFINITIONS
from apps.billing.services import upsert_official_plan
from apps.catalog.models import Genre, TagCategory


TAG_CATEGORIES = ["BUSINESS_CONTEXT", "MOOD", "ENERGY", "TIME_OF_DAY", "SEASON", "AUDIENCE", "INSTRUMENTATION", "STYLE", "USE_CASE"]
GENRES = ["Pop", "Rock", "Punk", "Jazz", "Electronica", "Ambient", "Clasica", "Lo-fi", "Funk", "Dance"]


class Command(BaseCommand):
    help = "Carga datos iniciales globales de BrandyManager."

    def handle(self, *args, **options):
        permissions = {}
        for definition in OFFICIAL_PERMISSIONS:
            code = definition["code"]
            permission, _ = Permission.objects.update_or_create(
                code=code,
                defaults={
                    "name": definition["name"],
                    "module": definition["module"],
                    "permission_level": definition["level"],
                    "is_active": True,
                },
            )
            permissions[code] = permission
        for code, definition in PLATFORM_ROLE_DEFINITIONS.items():
            role, _ = PlatformRole.objects.update_or_create(
                code=code,
                defaults={"name": definition["name"], "is_system": True, "is_active": True},
            )
            for permission_code in definition["permissions"]:
                PlatformRolePermission.objects.get_or_create(role=role, permission=permissions[permission_code])
        for code, definition in COMPANY_ROLE_DEFINITIONS.items():
            role, _ = CompanyRole.objects.update_or_create(
                company=None,
                code=code,
                defaults={
                    "name": definition["name"],
                    "description": definition["description"],
                    "is_system_template": True,
                    "is_editable": False,
                    "is_active": True,
                },
            )
            for permission_code in definition["permissions"]:
                CompanyRolePermission.objects.get_or_create(role=role, permission=permissions[permission_code])
        for code in OFFICIAL_PLAN_DEFINITIONS:
            upsert_official_plan(code=code)
        for index, code in enumerate(TAG_CATEGORIES):
            TagCategory.objects.update_or_create(
                code=code,
                defaults={"name": code.replace("_", " ").title(), "sort_order": index, "is_active": True},
            )
        for index, name in enumerate(GENRES):
            Genre.objects.update_or_create(
                slug=name.lower().replace(" ", "-"),
                defaults={"name": name, "sort_order": index, "is_active": True},
            )
        self.stdout.write(self.style.SUCCESS("Datos iniciales cargados."))
