from django.urls import path

from apps.devices import views
from apps.devices import internal_views


urlpatterns = [
    path("player-token/introspect/", views.InternalDeviceTokenIntrospectionView.as_view(), name="player-token-introspect"),
    path("player/runtime/", internal_views.InternalPlayerRuntimeView.as_view(), name="player-runtime"),
    path("player/telemetry/", internal_views.InternalPlayerTelemetryView.as_view(), name="player-telemetry"),
    path("player/commands/", internal_views.InternalPlayerCommandsView.as_view(), name="player-commands"),
    path("player/commands/<uuid:command_id>/ack/", internal_views.InternalPlayerCommandAckView.as_view(), name="player-command-ack"),
]
