from django.contrib import admin

from apps.scheduling import models


for model in (
    models.Schedule,
    models.ScheduleBlock,
    models.ScheduleException,
    models.ScheduleAssignment,
):
    admin.site.register(model)
