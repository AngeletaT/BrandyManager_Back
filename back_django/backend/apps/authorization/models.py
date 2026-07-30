from django.core.exceptions import ValidationError
from django.db import models

from shared.db.models import TimeStampedUUIDModel, UUIDModel


class Permission(TimeStampedUUIDModel):
    class PermissionLevel(models.TextChoices):
        PLATFORM = "PLATFORM", "Platform"
        COMPANY = "COMPANY", "Company"

    code = models.CharField(max_length=120, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    module = models.CharField(max_length=80, db_index=True)
    permission_level = models.CharField(max_length=20, choices=PermissionLevel.choices, db_index=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        indexes = [
            models.Index(fields=["permission_level", "is_active"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["updated_at"]),
        ]

    def __str__(self):
        return self.code


class PlatformRole(TimeStampedUUIDModel):
    code = models.CharField(max_length=80, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    is_system = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        indexes = [
            models.Index(fields=["is_active"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["updated_at"]),
        ]


class PlatformRolePermission(UUIDModel):
    role = models.ForeignKey(PlatformRole, on_delete=models.PROTECT, related_name="role_permissions")
    permission = models.ForeignKey(Permission, on_delete=models.PROTECT, related_name="platform_role_permissions")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["role", "permission"], name="uniq_platform_role_permission"),
        ]

    def clean(self):
        super().clean()
        if self.permission.permission_level != Permission.PermissionLevel.PLATFORM:
            raise ValidationError({"permission": "El permiso debe ser de plataforma."})


class UserPlatformRole(UUIDModel):
    user = models.ForeignKey("users.User", on_delete=models.PROTECT, related_name="platform_roles")
    role = models.ForeignKey(PlatformRole, on_delete=models.PROTECT, related_name="user_assignments")
    assigned_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_platform_roles")
    assigned_at = models.DateTimeField(auto_now_add=True, db_index=True)
    revoked_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "role"], condition=models.Q(revoked_at__isnull=True), name="uniq_active_user_platform_role"),
        ]
        indexes = [
            models.Index(fields=["user", "revoked_at"]),
            models.Index(fields=["assigned_at"]),
        ]


class CompanyRole(TimeStampedUUIDModel):
    company = models.ForeignKey("organizations.Company", on_delete=models.PROTECT, null=True, blank=True, related_name="roles")
    code = models.CharField(max_length=80)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    is_system_template = models.BooleanField(default=False)
    is_editable = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="created_company_roles")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["company", "code"], name="uniq_company_role_company_code"),
            models.UniqueConstraint(fields=["code"], condition=models.Q(company__isnull=True), name="uniq_global_company_role_code"),
        ]
        indexes = [
            models.Index(fields=["company", "is_active"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["updated_at"]),
        ]


class CompanyRolePermission(UUIDModel):
    role = models.ForeignKey(CompanyRole, on_delete=models.PROTECT, related_name="role_permissions")
    permission = models.ForeignKey(Permission, on_delete=models.PROTECT, related_name="company_role_permissions")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["role", "permission"], name="uniq_company_role_permission"),
        ]

    def clean(self):
        super().clean()
        if self.permission.permission_level != Permission.PermissionLevel.COMPANY:
            raise ValidationError({"permission": "El permiso debe ser de empresa."})
