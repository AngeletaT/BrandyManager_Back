from django.urls import path

from apps.playlists import views


urlpatterns = [
    path("", views.PlaylistListCreateView.as_view(), name="playlist-list"),
    path("<uuid:playlist_id>/", views.PlaylistDetailView.as_view(), name="playlist-detail"),
    path("<uuid:playlist_id>/items/", views.PlaylistItemListView.as_view(), name="playlist-item-list"),
    path("<uuid:playlist_id>/items/order/", views.PlaylistItemOrderView.as_view(), name="playlist-item-order"),
    path("<uuid:playlist_id>/items/<uuid:item_id>/", views.PlaylistItemDetailView.as_view(), name="playlist-item-detail"),
    path("<uuid:playlist_id>/duplicate/", views.PlaylistDuplicateView.as_view(), name="playlist-duplicate"),
    path("<uuid:playlist_id>/publish/", views.PlaylistPublishView.as_view(), name="playlist-publish"),
    path("<uuid:playlist_id>/published-version/", views.PlaylistPublishedVersionView.as_view(), name="playlist-published-version"),
    path("<uuid:playlist_id>/archive/", views.PlaylistArchiveView.as_view(), name="playlist-archive"),
    path("<uuid:playlist_id>/reactivate/", views.PlaylistReactivateView.as_view(), name="playlist-reactivate"),
]
