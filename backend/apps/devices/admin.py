from django.contrib import admin

from apps.devices import models


for model in (
    models.Device,
    models.DeviceZoneAssignment,
    models.DeviceCredential,
    models.DeviceCommand,
    models.DeviceEvent,
    models.DeviceState,
    models.DeviceSync,
    models.DeviceCachedAsset,
):
    admin.site.register(model)
