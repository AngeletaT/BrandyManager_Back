from django.core.exceptions import ValidationError
from django.db import models

from shared.db.models import TimeStampedUUIDModel, UUIDModel


class Playlist(TimeStampedUUIDModel):
    class PlaylistType(models.TextChoices):
        MANUAL = "MANUAL", "Manual"
        RULE_BASED = "RULE_BASED", "Rule based"

    class Visibility(models.TextChoices):
        GLOBAL = "GLOBAL", "Global"
        PRIVATE = "PRIVATE", "Private"
        SHARED = "SHARED", "Shared"

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PUBLISHED = "PUBLISHED", "Published"
        DISABLED = "DISABLED", "Disabled"
        ARCHIVED = "ARCHIVED", "Archived"

    owner_company = models.ForeignKey("organizations.Company", on_delete=models.PROTECT, null=True, blank=True, related_name="playlists")
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    playlist_type = models.CharField(max_length=20, choices=PlaylistType.choices, default=PlaylistType.MANUAL)
    visibility = models.CharField(max_length=20, choices=Visibility.choices, default=Visibility.GLOBAL)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)
    current_version = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="created_playlists")
    published_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["owner_company", "code"], name="uniq_playlist_owner_code"),
            models.UniqueConstraint(fields=["code"], condition=models.Q(owner_company__isnull=True), name="uniq_global_playlist_code"),
        ]
        indexes = [
            models.Index(fields=["owner_company", "status"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["updated_at"]),
        ]


class PlaylistItem(TimeStampedUUIDModel):
    playlist = models.ForeignKey(Playlist, on_delete=models.PROTECT, related_name="items")
    song = models.ForeignKey("catalog.Song", on_delete=models.PROTECT, related_name="playlist_items")
    position = models.PositiveIntegerField()
    weight = models.PositiveIntegerField(default=1)
    active_from = models.DateTimeField(null=True, blank=True)
    active_until = models.DateTimeField(null=True, blank=True)
    added_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="added_playlist_items")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["playlist", "position"], name="uniq_playlist_item_position"),
        ]
        indexes = [
            models.Index(fields=["playlist", "position"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["updated_at"]),
        ]


class PlaylistSnapshot(UUIDModel):
    class Status(models.TextChoices):
        CREATED = "CREATED", "Created"
        PUBLISHED = "PUBLISHED", "Published"
        SUPERSEDED = "SUPERSEDED", "Superseded"

    playlist = models.ForeignKey(Playlist, on_delete=models.PROTECT, related_name="snapshots")
    version = models.PositiveIntegerField()
    checksum = models.CharField(max_length=128)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.CREATED)
    published_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="published_playlist_snapshots")
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["playlist", "version"], name="uniq_playlist_snapshot_version"),
        ]
        indexes = [
            models.Index(fields=["playlist", "status"]),
            models.Index(fields=["created_at"]),
        ]


class PlaylistSnapshotItem(UUIDModel):
    snapshot = models.ForeignKey(PlaylistSnapshot, on_delete=models.PROTECT, related_name="items")
    song = models.ForeignKey("catalog.Song", on_delete=models.PROTECT, related_name="playlist_snapshot_items")
    position = models.PositiveIntegerField()
    weight = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["snapshot", "position"], name="uniq_playlist_snapshot_item_position"),
        ]


class Channel(TimeStampedUUIDModel):
    class Visibility(models.TextChoices):
        GLOBAL = "GLOBAL", "Global"
        PRIVATE = "PRIVATE", "Private"
        SHARED = "SHARED", "Shared"

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PUBLISHED = "PUBLISHED", "Published"
        DISABLED = "DISABLED", "Disabled"
        ARCHIVED = "ARCHIVED", "Archived"

    owner_company = models.ForeignKey("organizations.Company", on_delete=models.PROTECT, null=True, blank=True, related_name="channels")
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    visibility = models.CharField(max_length=20, choices=Visibility.choices, default=Visibility.GLOBAL)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)
    cover_storage_key = models.CharField(max_length=512, blank=True)
    created_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="created_channels")
    published_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["owner_company", "code"], name="uniq_channel_owner_code"),
            models.UniqueConstraint(fields=["code"], condition=models.Q(owner_company__isnull=True), name="uniq_global_channel_code"),
        ]


class ChannelPlaylist(TimeStampedUUIDModel):
    channel = models.ForeignKey(Channel, on_delete=models.PROTECT, related_name="channel_playlists")
    playlist = models.ForeignKey(Playlist, on_delete=models.PROTECT, related_name="channel_playlists")
    weight = models.PositiveIntegerField(default=1)
    priority = models.IntegerField(default=0)
    active_from = models.DateTimeField(null=True, blank=True)
    active_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["channel", "playlist"], name="uniq_channel_playlist"),
        ]


class ChannelPolicy(TimeStampedUUIDModel):
    class OrderMode(models.TextChoices):
        SEQUENTIAL = "SEQUENTIAL", "Sequential"
        SHUFFLE = "SHUFFLE", "Shuffle"
        WEIGHTED = "WEIGHTED", "Weighted"

    channel = models.OneToOneField(Channel, on_delete=models.PROTECT, related_name="policy")
    order_mode = models.CharField(max_length=20, choices=OrderMode.choices, default=OrderMode.SHUFFLE)
    repeat_song_gap_count = models.PositiveIntegerField(default=10)
    max_same_genre_in_row = models.PositiveIntegerField(default=3)
    avoid_same_tag_in_row = models.BooleanField(default=True)
    crossfade_ms = models.PositiveIntegerField(default=0)
    fade_in_ms = models.PositiveIntegerField(default=0)
    fade_out_ms = models.PositiveIntegerField(default=0)
    normalize_loudness = models.BooleanField(default=True)
    target_lufs = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    settings = models.JSONField(default=dict, blank=True)


class ContentAccessGrant(UUIDModel):
    company = models.ForeignKey("organizations.Company", on_delete=models.PROTECT, related_name="content_access_grants")
    audio_content = models.ForeignKey("catalog.AudioContent", on_delete=models.PROTECT, null=True, blank=True, related_name="access_grants")
    playlist = models.ForeignKey(Playlist, on_delete=models.PROTECT, null=True, blank=True, related_name="access_grants")
    channel = models.ForeignKey(Channel, on_delete=models.PROTECT, null=True, blank=True, related_name="access_grants")
    granted_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="granted_content_access")
    granted_at = models.DateTimeField(db_index=True)
    revoked_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                name="content_access_exactly_one_target",
                check=(
                    models.Q(audio_content__isnull=False, playlist__isnull=True, channel__isnull=True)
                    | models.Q(audio_content__isnull=True, playlist__isnull=False, channel__isnull=True)
                    | models.Q(audio_content__isnull=True, playlist__isnull=True, channel__isnull=False)
                ),
            )
        ]
