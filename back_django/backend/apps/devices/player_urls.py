from django.urls import path

from apps.devices import views


urlpatterns = [
    path("activation/validate/", views.PlayerActivationValidateView.as_view(), name="player-activation-validate"),
    path("activation/complete/", views.PlayerActivationCompleteView.as_view(), name="player-activation-complete"),
    path("token/refresh/", views.PlayerTokenRefreshView.as_view(), name="player-token-refresh"),
    path("logout/", views.PlayerLogoutView.as_view(), name="player-logout"),
    path("session/", views.PlayerSessionView.as_view(), name="player-session"),
]
