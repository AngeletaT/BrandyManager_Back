from django.contrib import admin
from django.urls import include, path


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/catalog/", include("apps.catalog.urls")),
    path("api/channels/", include("apps.playlists.channel_urls")),
    path("api/devices/", include("apps.devices.urls")),
    path("api/internal/", include("apps.devices.internal_urls")),
    path("api/internal/", include("apps.catalog.internal_urls")),
    path("api/onboarding/", include("apps.onboarding.urls")),
    path("api/organizations/", include("apps.organizations.urls")),
    path("api/playlists/", include("apps.playlists.urls")),
    path("api/player/", include("apps.devices.player_urls")),
    path("api/scheduling/", include("apps.scheduling.urls")),
    path("api/users/", include("apps.users.urls")),
]
