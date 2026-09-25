from django.urls import path

from apps.catalog.internal_views import InternalAudioAssetStreamView


urlpatterns = [
    path("audio/assets/<uuid:asset_id>/stream/", InternalAudioAssetStreamView.as_view(), name="internal-audio-asset-stream"),
]
