from django.urls import path

from apps.devices import views


urlpatterns = [
    path("", views.DeviceListCreateView.as_view(), name="device-list"),
    path("<uuid:device_id>/", views.DeviceDetailView.as_view(), name="device-detail"),
    path("<uuid:device_id>/zone/", views.DeviceZoneView.as_view(), name="device-zone"),
    path("<uuid:device_id>/suspend/", views.DeviceSuspendView.as_view(), name="device-suspend"),
    path("<uuid:device_id>/reactivate/", views.DeviceReactivateView.as_view(), name="device-reactivate"),
    path("<uuid:device_id>/archive/", views.DeviceArchiveView.as_view(), name="device-archive"),
    path("<uuid:device_id>/activation-codes/", views.DeviceActivationCodeView.as_view(), name="device-activation-code"),
    path("<uuid:device_id>/revoke/", views.DeviceRevokeView.as_view(), name="device-revoke"),
    path("<uuid:device_id>/commands/", views.DeviceCommandCreateView.as_view(), name="device-command-create"),
    path("<uuid:device_id>/events/", views.DeviceEventListView.as_view(), name="device-event-list"),
]
