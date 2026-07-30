from django.core.exceptions import ValidationError
from django.db import models

from shared.db.models import TimeStampedUUIDModel, UUIDModel, validate_date_range


class Company(TimeStampedUUIDModel):
    class Status(models.TextChoices):
        TRIAL = "TRIAL", "Trial"
        ACTIVE = "ACTIVE", "Active"
        SUSPENDED = "SUSPENDED", "Suspended"
        CANCELLED = "CANCELLED", "Cancelled"
        ARCHIVED = "ARCHIVED", "Archived"

    legal_name = models.CharField(max_length=255)
    trade_name = models.CharField(max_length=255, db_index=True)
    tax_id = models.CharField(max_length=64, db_index=True)
    billing_email = models.EmailField()
    contact_email = models.EmailField()
    phone = models.CharField(max_length=50, blank=True)
    country_code = models.CharField(max_length=2)
    default_timezone = models.CharField(max_length=64, default="Europe/Madrid")
    default_language = models.CharField(max_length=10, default="es")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.TRIAL, db_index=True)
    settings = models.JSONField(default=dict, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["tax_id"]),
            models.Index(fields=["trade_name"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["updated_at"]),
        ]

    def __str__(self):
        return self.trade_name or self.legal_name


class CompanyMembership(TimeStampedUUIDModel):
    class Status(models.TextChoices):
        INVITED = "INVITED", "Invited"
        ACTIVE = "ACTIVE", "Active"
        SUSPENDED = "SUSPENDED", "Suspended"
        REVOKED = "REVOKED", "Revoked"

    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="memberships")
    user = models.ForeignKey("users.User", on_delete=models.PROTECT, related_name="company_memberships")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.INVITED, db_index=True)
    invited_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="sent_company_invitations")
    invited_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    last_access_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["company", "user"], name="uniq_company_membership_user"),
        ]
        indexes = [
            models.Index(fields=["company", "status"]),
            models.Index(fields=["user", "status"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["updated_at"]),
        ]


class OrganizationalUnit(TimeStampedUUIDModel):
    class UnitType(models.TextChoices):
        BRAND = "BRAND", "Brand"
        REGION = "REGION", "Region"
        DIVISION = "DIVISION", "Division"
        LEGAL_ENTITY = "LEGAL_ENTITY", "Legal entity"
        FRANCHISE = "FRANCHISE", "Franchise"
        OTHER = "OTHER", "Other"

    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="organizational_units")
    parent = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="children")
    unit_type = models.CharField(max_length=30, choices=UnitType.choices)
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=64)
    description = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["company", "code"], name="uniq_org_unit_company_code"),
        ]
        indexes = [
            models.Index(fields=["company", "unit_type"]),
            models.Index(fields=["company", "is_active"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["updated_at"]),
        ]

    def clean(self):
        super().clean()
        if self.parent_id:
            if self.parent_id == self.id:
                raise ValidationError({"parent": "Una unidad no puede ser padre de si misma."})
            if self.parent.company_id != self.company_id:
                raise ValidationError({"parent": "El padre debe pertenecer a la misma empresa."})
            ancestor = self.parent
            while ancestor:
                if ancestor.id == self.id:
                    raise ValidationError({"parent": "No se permiten ciclos jerarquicos."})
                ancestor = ancestor.parent


class Site(TimeStampedUUIDModel):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        INACTIVE = "INACTIVE", "Inactive"
        TEMPORARILY_CLOSED = "TEMPORARILY_CLOSED", "Temporarily closed"
        ARCHIVED = "ARCHIVED", "Archived"

    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="sites")
    organizational_unit = models.ForeignKey(OrganizationalUnit, on_delete=models.SET_NULL, null=True, blank=True, related_name="sites")
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=64)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    address_line_1 = models.CharField(max_length=255)
    address_line_2 = models.CharField(max_length=255, blank=True)
    postal_code = models.CharField(max_length=20)
    city = models.CharField(max_length=120)
    province = models.CharField(max_length=120, blank=True)
    country_code = models.CharField(max_length=2)
    timezone = models.CharField(max_length=64)
    contact_name = models.CharField(max_length=255, blank=True)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=50, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["company", "code"], name="uniq_site_company_code"),
        ]
        indexes = [
            models.Index(fields=["company", "status"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["updated_at"]),
        ]

    def clean(self):
        super().clean()
        if self.organizational_unit_id and self.organizational_unit.company_id != self.company_id:
            raise ValidationError({"organizational_unit": "La unidad debe pertenecer a la misma empresa."})


class Zone(TimeStampedUUIDModel):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        INACTIVE = "INACTIVE", "Inactive"
        SUSPENDED = "SUSPENDED", "Suspended"
        ARCHIVED = "ARCHIVED", "Archived"

    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="zones")
    site = models.ForeignKey(Site, on_delete=models.PROTECT, related_name="zones")
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=64)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    timezone = models.CharField(max_length=64, null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["site", "code"], name="uniq_zone_site_code"),
        ]
        indexes = [
            models.Index(fields=["company", "status"]),
            models.Index(fields=["site", "status"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["updated_at"]),
        ]

    def clean(self):
        super().clean()
        if self.site_id and self.site.company_id != self.company_id:
            raise ValidationError({"company": "La empresa de la zona debe coincidir con la sede."})

    @property
    def effective_timezone(self):
        return self.timezone or self.site.timezone


class ResourceGroup(TimeStampedUUIDModel):
    class GroupType(models.TextChoices):
        SITE = "SITE", "Site"
        ZONE = "ZONE", "Zone"

    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="resource_groups")
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    group_type = models.CharField(max_length=10, choices=GroupType.choices, db_index=True)
    is_dynamic = models.BooleanField(default=False)
    filter_definition = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["company", "group_type", "name"], name="uniq_resource_group_company_type_name"),
        ]
        indexes = [
            models.Index(fields=["company", "group_type", "is_active"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["updated_at"]),
        ]


class ResourceGroupSite(UUIDModel):
    group = models.ForeignKey(ResourceGroup, on_delete=models.PROTECT, related_name="site_members")
    site = models.ForeignKey(Site, on_delete=models.PROTECT, related_name="resource_group_memberships")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["group", "site"], name="uniq_resource_group_site"),
        ]

    def clean(self):
        super().clean()
        if self.group.group_type != ResourceGroup.GroupType.SITE:
            raise ValidationError({"group": "El grupo debe ser de tipo SITE."})
        if self.group.company_id != self.site.company_id:
            raise ValidationError({"site": "La sede debe pertenecer a la misma empresa que el grupo."})


class ResourceGroupZone(UUIDModel):
    group = models.ForeignKey(ResourceGroup, on_delete=models.PROTECT, related_name="zone_members")
    zone = models.ForeignKey(Zone, on_delete=models.PROTECT, related_name="resource_group_memberships")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["group", "zone"], name="uniq_resource_group_zone"),
        ]

    def clean(self):
        super().clean()
        if self.group.group_type != ResourceGroup.GroupType.ZONE:
            raise ValidationError({"group": "El grupo debe ser de tipo ZONE."})
        if self.group.company_id != self.zone.company_id:
            raise ValidationError({"zone": "La zona debe pertenecer a la misma empresa que el grupo."})


class ResourceScope(TimeStampedUUIDModel):
    class ScopeType(models.TextChoices):
        COMPANY = "COMPANY", "Company"
        ORGANIZATIONAL_UNIT = "ORGANIZATIONAL_UNIT", "Organizational unit"
        SITE = "SITE", "Site"
        ZONE = "ZONE", "Zone"
        RESOURCE_GROUP = "RESOURCE_GROUP", "Resource group"

    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="resource_scopes")
    scope_type = models.CharField(max_length=30, choices=ScopeType.choices, db_index=True)
    organizational_unit = models.ForeignKey(OrganizationalUnit, on_delete=models.PROTECT, null=True, blank=True, related_name="resource_scopes")
    site = models.ForeignKey(Site, on_delete=models.PROTECT, null=True, blank=True, related_name="resource_scopes")
    zone = models.ForeignKey(Zone, on_delete=models.PROTECT, null=True, blank=True, related_name="resource_scopes")
    resource_group = models.ForeignKey(ResourceGroup, on_delete=models.PROTECT, null=True, blank=True, related_name="resource_scopes")
    name = models.CharField(max_length=255)
    is_system_generated = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.CheckConstraint(
                name="resource_scope_exactly_one_target",
                check=(
                    models.Q(scope_type="COMPANY", organizational_unit__isnull=True, site__isnull=True, zone__isnull=True, resource_group__isnull=True)
                    | models.Q(scope_type="ORGANIZATIONAL_UNIT", organizational_unit__isnull=False, site__isnull=True, zone__isnull=True, resource_group__isnull=True)
                    | models.Q(scope_type="SITE", organizational_unit__isnull=True, site__isnull=False, zone__isnull=True, resource_group__isnull=True)
                    | models.Q(scope_type="ZONE", organizational_unit__isnull=True, site__isnull=True, zone__isnull=False, resource_group__isnull=True)
                    | models.Q(scope_type="RESOURCE_GROUP", organizational_unit__isnull=True, site__isnull=True, zone__isnull=True, resource_group__isnull=False)
                ),
            ),
            models.UniqueConstraint(fields=["company"], condition=models.Q(scope_type="COMPANY"), name="uniq_company_scope"),
            models.UniqueConstraint(fields=["organizational_unit"], condition=models.Q(scope_type="ORGANIZATIONAL_UNIT"), name="uniq_org_unit_scope"),
            models.UniqueConstraint(fields=["site"], condition=models.Q(scope_type="SITE"), name="uniq_site_scope"),
            models.UniqueConstraint(fields=["zone"], condition=models.Q(scope_type="ZONE"), name="uniq_zone_scope"),
            models.UniqueConstraint(fields=["resource_group"], condition=models.Q(scope_type="RESOURCE_GROUP"), name="uniq_resource_group_scope"),
        ]
        indexes = [
            models.Index(fields=["company", "scope_type"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["updated_at"]),
        ]

    def clean(self):
        super().clean()
        selected = self.organizational_unit or self.site or self.zone or self.resource_group
        if selected and selected.company_id != self.company_id:
            raise ValidationError({"company": "El recurso del ambito debe pertenecer a la empresa indicada."})


class MembershipGrant(TimeStampedUUIDModel):
    membership = models.ForeignKey(CompanyMembership, on_delete=models.PROTECT, related_name="grants")
    role = models.ForeignKey("authorization.CompanyRole", on_delete=models.PROTECT, related_name="membership_grants")
    scope = models.ForeignKey(ResourceScope, on_delete=models.PROTECT, related_name="membership_grants")
    policy_overrides = models.JSONField(default=dict, blank=True)
    starts_at = models.DateTimeField(null=True, blank=True, db_index=True)
    ends_at = models.DateTimeField(null=True, blank=True, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    assigned_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_membership_grants")

    class Meta:
        indexes = [
            models.Index(fields=["membership", "is_active"]),
            models.Index(fields=["scope", "is_active"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["updated_at"]),
        ]

    def clean(self):
        super().clean()
        validate_date_range(starts_at=self.starts_at, ends_at=self.ends_at)
        company_id = self.membership.company_id
        if self.scope.company_id != company_id:
            raise ValidationError({"scope": "El ambito debe pertenecer a la misma empresa que la membresia."})
        if self.role.company_id and self.role.company_id != company_id:
            raise ValidationError({"role": "El rol personalizado debe pertenecer a la misma empresa que la membresia."})


class MembershipPermissionOverride(TimeStampedUUIDModel):
    class Effect(models.TextChoices):
        ALLOW = "ALLOW", "Allow"
        DENY = "DENY", "Deny"

    membership = models.ForeignKey(CompanyMembership, on_delete=models.PROTECT, related_name="permission_overrides")
    scope = models.ForeignKey(ResourceScope, on_delete=models.PROTECT, related_name="permission_overrides")
    permission = models.ForeignKey("authorization.Permission", on_delete=models.PROTECT, related_name="membership_overrides")
    effect = models.CharField(max_length=10, choices=Effect.choices)
    constraints = models.JSONField(default=dict, blank=True)
    starts_at = models.DateTimeField(null=True, blank=True, db_index=True)
    ends_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="created_permission_overrides")

    class Meta:
        indexes = [
            models.Index(fields=["membership", "effect"]),
            models.Index(fields=["scope"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["updated_at"]),
        ]

    def clean(self):
        super().clean()
        validate_date_range(starts_at=self.starts_at, ends_at=self.ends_at)
        if self.scope.company_id != self.membership.company_id:
            raise ValidationError({"scope": "El ambito debe pertenecer a la misma empresa que la membresia."})
        if self.permission.permission_level != "COMPANY":
            raise ValidationError({"permission": "Solo se pueden aplicar permisos de empresa."})
