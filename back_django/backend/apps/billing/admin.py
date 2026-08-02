from django.contrib import admin

from apps.billing import models


@admin.register(models.Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "billing_interval", "base_price", "currency", "is_public", "is_active")
    list_filter = ("billing_interval", "is_public", "is_active")
    search_fields = ("code", "name")


@admin.register(models.Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("id", "company", "plan", "status", "trial_ends_at", "current_period_end", "blocked_reason")
    list_filter = ("status", "plan", "trial_ends_at")
    search_fields = ("company__trade_name", "company__legal_name", "provider_customer_id", "provider_subscription_id")
    readonly_fields = ("created_at", "updated_at")


for model in (models.License, models.LicenseAssignment):
    admin.site.register(model)
