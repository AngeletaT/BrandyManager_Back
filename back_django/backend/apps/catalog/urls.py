from django.urls import path

from apps.catalog import views
from apps.catalog.internal_views import InternalSongIngestView


urlpatterns = [
    path("genres/", views.GenreListView.as_view(), name="catalog-genre-list"),
    path("tags/", views.TagListView.as_view(), name="catalog-tag-list"),
    path("songs/", views.SongListView.as_view(), name="catalog-song-list"),
    path("songs/<uuid:song_id>/", views.SongDetailView.as_view(), name="catalog-song-detail"),
    path("internal/songs/", InternalSongIngestView.as_view(), name="internal-catalog-song-ingest"),
]
