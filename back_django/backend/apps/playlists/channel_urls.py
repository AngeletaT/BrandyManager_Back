from django.urls import path

from apps.playlists import views


urlpatterns = [
    path("", views.ChannelListCreateView.as_view(), name="channel-list"),
    path("zone-assignments/<uuid:zone_id>/", views.ZoneChannelAssignmentView.as_view(), name="channel-zone-assignment"),
    path("<uuid:channel_id>/", views.ChannelDetailView.as_view(), name="channel-detail"),
    path("<uuid:channel_id>/policy/", views.ChannelPolicyView.as_view(), name="channel-policy"),
    path("<uuid:channel_id>/playlists/", views.ChannelPlaylistConfigView.as_view(), name="channel-playlists"),
    path("<uuid:channel_id>/duplicate/", views.ChannelDuplicateView.as_view(), name="channel-duplicate"),
    path("<uuid:channel_id>/publish/", views.ChannelPublishView.as_view(), name="channel-publish"),
    path("<uuid:channel_id>/published-configuration/", views.ChannelPublishedConfigurationView.as_view(), name="channel-published-configuration"),
    path("<uuid:channel_id>/zones/", views.ChannelZonesView.as_view(), name="channel-zones"),
    path("<uuid:channel_id>/archive/", views.ChannelArchiveView.as_view(), name="channel-archive"),
    path("<uuid:channel_id>/reactivate/", views.ChannelReactivateView.as_view(), name="channel-reactivate"),
]
