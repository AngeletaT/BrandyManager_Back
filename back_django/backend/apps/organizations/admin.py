from django.contrib import admin

from apps.organizations import models


for model in (
    models.Company,
    models.CompanyInvitation,
    models.CompanyMembership,
    models.OrganizationalUnit,
    models.Site,
    models.Zone,
    models.ZoneChannelAssignment,
    models.ResourceGroup,
    models.ResourceGroupSite,
    models.ResourceGroupZone,
    models.ResourceScope,
    models.MembershipGrant,
    models.MembershipPermissionOverride,
):
    admin.site.register(model)
