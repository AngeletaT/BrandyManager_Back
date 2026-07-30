from django.contrib import admin

from apps.support import models


for model in (models.Incident, models.IncidentEvent, models.Notification):
    admin.site.register(model)
