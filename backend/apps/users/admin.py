from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from apps.users.models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        (
            "brandyManager",
            {
                "fields": (
                    "role",
                    "phone",
                    "company_name",
                )
            },
        ),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        (
            "brandyManager",
            {
                "fields": (
                    "email",
                    "first_name",
                    "last_name",
                    "role",
                    "phone",
                    "company_name",
                )
            },
        ),
    )
    list_display = (
        "id",
        "username",
        "email",
        "first_name",
        "last_name",
        "role",
        "is_active",
        "is_staff",
        "date_joined",
    )
    list_filter = ("role", "is_active", "is_staff", "is_superuser")
    search_fields = ("username", "email", "first_name", "last_name", "company_name")
