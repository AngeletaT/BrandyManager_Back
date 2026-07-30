from django.contrib import admin

from apps.campaigns import models


for model in (
    models.Campaign,
    models.CampaignMessage,
    models.CampaignRule,
    models.CampaignRuleTime,
    models.CampaignTarget,
):
    admin.site.register(model)
