from django.contrib import admin

from apps.playback import models


for model in (
    models.PlaybackPolicy,
    models.PlaybackPolicyAllowedChannel,
    models.PlaybackPolicyAssignment,
    models.ContentManifest,
    models.ContentManifestItem,
    models.ZoneOperationalSnapshot,
    models.PlaybackSession,
    models.PlaybackEvent,
):
    admin.site.register(model)
