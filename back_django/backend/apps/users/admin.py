from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from apps.users.models import User, UserActionToken


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    ordering = ("email",)
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Datos personales", {"fields": ("first_name", "last_name")}),
        ("Seguridad", {"fields": ("mfa_enabled", "email_verified_at")}),
        ("Permisos Django", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Fechas", {"fields": ("last_login", "date_joined", "created_at", "updated_at")}),
    )
    add_fieldsets = (
        (
            "brandyManager",
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "password1",
                    "password2",
                    "first_name",
                    "last_name",
                )
            },
        ),
    )
    list_display = (
        "id",
        "email",
        "first_name",
        "last_name",
        "is_active",
        "is_staff",
        "date_joined",
    )
    readonly_fields = ("created_at", "updated_at")
    list_filter = ("is_active", "is_staff", "is_superuser", "mfa_enabled")
    search_fields = ("email", "first_name", "last_name")


@admin.register(UserActionToken)
class UserActionTokenAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "purpose", "expires_at", "consumed_at", "revoked_at", "created_at")
    list_filter = ("purpose", "consumed_at", "revoked_at", "expires_at")
    search_fields = ("user__email", "token_hash")
    readonly_fields = ("id", "token_hash", "created_at")
