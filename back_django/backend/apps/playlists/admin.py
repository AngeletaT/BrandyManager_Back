from django.contrib import admin

from apps.playlists import models


for model in (
    models.Playlist,
    models.PlaylistItem,
    models.PlaylistSnapshot,
    models.PlaylistSnapshotItem,
    models.Channel,
    models.ChannelPlaylist,
    models.ChannelPolicy,
    models.ChannelSnapshot,
    models.ChannelSnapshotPlaylist,
    models.ContentAccessGrant,
):
    admin.site.register(model)
