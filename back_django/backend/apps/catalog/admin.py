from django.contrib import admin

from apps.catalog import models


class ReadOnlyCatalogAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


for model in (models.Genre, models.TagCategory, models.Tag):
    admin.site.register(model)

for model in (
    models.AudioContent,
    models.Song,
    models.SongTag,
    models.AudioMessage,
    models.AudioAsset,
    models.AudioAnalysis,
    models.UploadSession,
    models.ProcessingJob,
):
    admin.site.register(model, ReadOnlyCatalogAdmin)
