from django.core.exceptions import ValidationError
from django.db import models

from shared.db.models import TimeStampedUUIDModel, UUIDModel


class Plan(TimeStampedUUIDModel):
    class BillingInterval(models.TextChoices):
        MONTHLY = "MONTHLY", "Monthly"
        QUARTERLY = "QUARTERLY", "Quarterly"
        YEARLY = "YEARLY", "Yearly"
        CUSTOM = "CUSTOM", "Custom"

    code = models.CharField(max_length=80, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    billing_interval = models.CharField(max_length=20, choices=BillingInterval.choices)
    base_price = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3)
    included_licenses = models.PositiveIntegerField(default=0)
    features = models.JSONField(default=dict, blank=True)
    is_public = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        indexes = [
            models.Index(fields=["is_active", "is_public"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["updated_at"]),
        ]


class Subscription(TimeStampedUUIDModel):
    class Status(models.TextChoices):
        TRIAL = "TRIAL", "Trial"
        ACTIVE = "ACTIVE", "Active"
        PAST_DUE = "PAST_DUE", "Past due"
        SUSPENDED = "SUSPENDED", "Suspended"
        CANCELLED = "CANCELLED", "Cancelled"
        EXPIRED = "EXPIRED", "Expired"

    company = models.ForeignKey("organizations.Company", on_delete=models.PROTECT, related_name="subscriptions")
    plan = models.ForeignKey(Plan, on_delete=models.SET_NULL, null=True, blank=True, related_name="subscriptions")
    status = models.CharField(max_length=20, choices=Status.choices, db_index=True)
    started_at = models.DateTimeField(db_index=True)
    current_period_start = models.DateTimeField()
    current_period_end = models.DateTimeField(db_index=True)
    renews_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    license_quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3)
    billing_provider = models.CharField(max_length=80, blank=True)
    provider_customer_id = models.CharField(max_length=255, blank=True)
    provider_subscription_id = models.CharField(max_length=255, blank=True)
    commercial_terms = models.JSONField(default=dict, blank=True)
    plan_snapshot = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["company", "status"]),
            models.Index(fields=["current_period_end"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["updated_at"]),
        ]


class License(TimeStampedUUIDModel):
    class Status(models.TextChoices):
        AVAILABLE = "AVAILABLE", "Available"
        ASSIGNED = "ASSIGNED", "Assigned"
        SUSPENDED = "SUSPENDED", "Suspended"
        EXPIRED = "EXPIRED", "Expired"
        CANCELLED = "CANCELLED", "Cancelled"

    company = models.ForeignKey("organizations.Company", on_delete=models.PROTECT, related_name="licenses")
    subscription = models.ForeignKey(Subscription, on_delete=models.PROTECT, related_name="licenses")
    code = models.CharField(max_length=80)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.AVAILABLE, db_index=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    suspended_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["company", "code"], name="uniq_license_company_code"),
        ]
        indexes = [
            models.Index(fields=["company", "status"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["updated_at"]),
        ]

    def clean(self):
        super().clean()
        if self.subscription_id and self.subscription.company_id != self.company_id:
            raise ValidationError({"subscription": "La suscripcion debe pertenecer a la misma empresa."})


class LicenseAssignment(UUIDModel):
    company = models.ForeignKey("organizations.Company", on_delete=models.PROTECT, related_name="license_assignments")
    license = models.ForeignKey(License, on_delete=models.PROTECT, related_name="assignments")
    zone = models.ForeignKey("organizations.Zone", on_delete=models.PROTECT, related_name="license_assignments")
    assigned_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_licenses")
    assigned_at = models.DateTimeField(db_index=True)
    unassigned_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="unassigned_licenses")
    unassigned_at = models.DateTimeField(null=True, blank=True, db_index=True)
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["license"], condition=models.Q(unassigned_at__isnull=True), name="uniq_active_assignment_per_license"),
            models.UniqueConstraint(fields=["zone"], condition=models.Q(unassigned_at__isnull=True), name="uniq_active_license_per_zone"),
        ]
        indexes = [
            models.Index(fields=["company", "assigned_at"]),
            models.Index(fields=["zone", "unassigned_at"]),
            models.Index(fields=["created_at"]),
        ]

    def clean(self):
        super().clean()
        if self.license_id and self.license.company_id != self.company_id:
            raise ValidationError({"license": "La licencia debe pertenecer a la misma empresa."})
        if self.zone_id and self.zone.company_id != self.company_id:
            raise ValidationError({"zone": "La zona debe pertenecer a la misma empresa."})
