from django.core.management.base import BaseCommand

from apps.authorization.models import CompanyRole, Permission, PlatformRole
from apps.catalog.models import Genre, TagCategory


PERMISSIONS = [
    ("platform.companies.manage", "Empresas", "platform", "PLATFORM"),
    ("platform.content.manage", "Contenido", "platform", "PLATFORM"),
    ("platform.billing.manage", "Facturacion", "platform", "PLATFORM"),
    ("platform.support.manage", "Soporte", "platform", "PLATFORM"),
    ("company.settings.manage", "Gestionar ajustes", "company", "COMPANY"),
    ("company.members.manage", "Gestionar miembros", "company", "COMPANY"),
    ("sites.view", "Ver sedes", "sites", "COMPANY"),
    ("sites.manage", "Gestionar sedes", "sites", "COMPANY"),
    ("zones.view", "Ver zonas", "zones", "COMPANY"),
    ("zones.manage", "Gestionar zonas", "zones", "COMPANY"),
    ("licenses.view", "Ver licencias", "licenses", "COMPANY"),
    ("licenses.assign", "Asignar licencias", "licenses", "COMPANY"),
    ("channels.view", "Ver canales", "channels", "COMPANY"),
    ("channels.select", "Seleccionar canales", "channels", "COMPANY"),
    ("playback.view", "Ver reproduccion", "playback", "COMPANY"),
    ("playback.control", "Controlar reproduccion", "playback", "COMPANY"),
    ("playback.volume", "Modificar volumen", "playback", "COMPANY"),
    ("schedules.view", "Ver programaciones", "schedules", "COMPANY"),
    ("schedules.manage", "Gestionar programaciones", "schedules", "COMPANY"),
    ("campaigns.view", "Ver campanas", "campaigns", "COMPANY"),
    ("campaigns.manage", "Gestionar campanas", "campaigns", "COMPANY"),
    ("devices.view", "Ver dispositivos", "devices", "COMPANY"),
    ("devices.manage", "Gestionar dispositivos", "devices", "COMPANY"),
    ("audit.view", "Ver auditoria", "audit", "COMPANY"),
    ("billing.view", "Ver facturacion", "billing", "COMPANY"),
    ("billing.manage", "Gestionar facturacion", "billing", "COMPANY"),
]

PLATFORM_ROLES = [
    "SUPERADMIN",
    "INTERNAL_ADMIN",
    "CONTENT_MANAGER",
    "SUPPORT_AGENT",
    "BILLING_MANAGER",
    "INTERNAL_READ_ONLY",
]

COMPANY_ROLES = ["COMPANY_ADMIN", "REGIONAL_MANAGER", "SITE_MANAGER", "OPERATOR", "READ_ONLY"]
TAG_CATEGORIES = ["BUSINESS_CONTEXT", "MOOD", "ENERGY", "TIME_OF_DAY", "SEASON", "AUDIENCE", "INSTRUMENTATION", "STYLE", "USE_CASE"]
GENRES = ["Pop", "Rock", "Punk", "Jazz", "Electronica", "Ambient", "Clasica", "Lo-fi", "Funk", "Dance"]


class Command(BaseCommand):
    help = "Carga datos iniciales globales de BrandyManager."

    def handle(self, *args, **options):
        for code, name, module, level in PERMISSIONS:
            Permission.objects.update_or_create(
                code=code,
                defaults={
                    "name": name,
                    "module": module,
                    "permission_level": level,
                    "is_active": True,
                },
            )
        for code in PLATFORM_ROLES:
            PlatformRole.objects.update_or_create(
                code=code,
                defaults={"name": code.replace("_", " ").title(), "is_system": True, "is_active": True},
            )
        for code in COMPANY_ROLES:
            CompanyRole.objects.update_or_create(
                company=None,
                code=code,
                defaults={"name": code.replace("_", " ").title(), "is_system_template": True, "is_editable": False, "is_active": True},
            )
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
