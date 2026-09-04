from django.urls import path

from apps.catalog import views


urlpatterns = [
    path("genres/", views.GenreListView.as_view(), name="catalog-genre-list"),
    path("tags/", views.TagListView.as_view(), name="catalog-tag-list"),
    path("songs/", views.SongListView.as_view(), name="catalog-song-list"),
    path("songs/<uuid:song_id>/", views.SongDetailView.as_view(), name="catalog-song-detail"),
]
