from django.contrib import admin

from apps.billing import models


for model in (models.Plan, models.Subscription, models.License, models.LicenseAssignment):
    admin.site.register(model)
