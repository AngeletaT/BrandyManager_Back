from django.contrib import admin

from apps.catalog import models


for model in (
    models.Genre,
    models.TagCategory,
    models.Tag,
    models.AudioContent,
    models.Song,
    models.SongTag,
    models.AudioMessage,
    models.AudioAsset,
    models.AudioAnalysis,
    models.UploadSession,
    models.ProcessingJob,
):
    admin.site.register(model)
