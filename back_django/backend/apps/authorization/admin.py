from django.contrib import admin

from apps.authorization import models


for model in (
    models.Permission,
    models.PlatformRole,
    models.PlatformRolePermission,
    models.UserPlatformRole,
    models.CompanyRole,
    models.CompanyRolePermission,
):
    admin.site.register(model)
