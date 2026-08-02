from django.contrib import admin
from django.urls import include, path


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/onboarding/", include("apps.onboarding.urls")),
    path("api/users/", include("apps.users.urls")),
]
