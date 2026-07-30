from django.core.exceptions import ValidationError
from django.db import models

from shared.db.models import TimeStampedUUIDModel, UUIDModel, validate_date_range


class PlaybackPolicy(TimeStampedUUIDModel):
    company = models.ForeignKey("organizations.Company", on_delete=models.PROTECT, related_name="playback_policies")
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    default_volume = models.PositiveSmallIntegerField(default=60)
    minimum_volume = models.PositiveSmallIntegerField(default=0)
    maximum_volume = models.PositiveSmallIntegerField(default=100)
    allow_local_volume_change = models.BooleanField(default=True)
    allow_channel_change = models.BooleanField(default=False)
    allow_pause = models.BooleanField(default=False)
    allow_skip = models.BooleanField(default=False)
    allow_manual_message = models.BooleanField(default=False)
    lock_schedule = models.BooleanField(default=False)
    offline_cache_days = models.PositiveIntegerField(default=7)
    fallback_channel = models.ForeignKey("playlists.Channel", on_delete=models.SET_NULL, null=True, blank=True, related_name="fallback_for_policies")
    settings = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="created_playback_policies")

    class Meta:
        constraints = [
            models.CheckConstraint(name="playback_policy_volume_range", check=models.Q(minimum_volume__gte=0, maximum_volume__lte=100)),
        ]
        indexes = [
            models.Index(fields=["company"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["updated_at"]),
        ]

    def clean(self):
        super().clean()
        if not (0 <= self.minimum_volume <= self.default_volume <= self.maximum_volume <= 100):
            raise ValidationError({"default_volume": "Debe cumplirse 0 <= minimo <= defecto <= maximo <= 100."})
        if self.fallback_channel_id and self.fallback_channel.owner_company_id not in (None, self.company_id):
            raise ValidationError({"fallback_channel": "El canal fallback debe ser global o de la misma empresa."})


class PlaybackPolicyAllowedChannel(UUIDModel):
    policy = models.ForeignKey(PlaybackPolicy, on_delete=models.PROTECT, related_name="allowed_channels")
    channel = models.ForeignKey("playlists.Channel", on_delete=models.PROTECT, related_name="allowed_in_policies")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["policy", "channel"], name="uniq_policy_allowed_channel"),
        ]


class PlaybackPolicyAssignment(TimeStampedUUIDModel):
    company = models.ForeignKey("organizations.Company", on_delete=models.PROTECT, related_name="playback_policy_assignments")
    policy = models.ForeignKey(PlaybackPolicy, on_delete=models.PROTECT, related_name="assignments")
    scope = models.ForeignKey("organizations.ResourceScope", on_delete=models.PROTECT, related_name="playback_policy_assignments")
    priority = models.IntegerField(default=0, db_index=True)
    is_locked = models.BooleanField(default=False)
    starts_at = models.DateTimeField(null=True, blank=True, db_index=True)
    ends_at = models.DateTimeField(null=True, blank=True, db_index=True)
    assigned_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_playback_policies")
    is_active = models.BooleanField(default=True, db_index=True)

    def clean(self):
        super().clean()
        validate_date_range(starts_at=self.starts_at, ends_at=self.ends_at)
        if self.policy.company_id != self.company_id:
            raise ValidationError({"policy": "La politica debe pertenecer a la misma empresa."})
        if self.scope.company_id != self.company_id:
            raise ValidationError({"scope": "El ambito debe pertenecer a la misma empresa."})


class ContentManifest(UUIDModel):
    class Status(models.TextChoices):
        GENERATING = "GENERATING", "Generating"
        READY = "READY", "Ready"
        SUPERSEDED = "SUPERSEDED", "Superseded"
        ERROR = "ERROR", "Error"

    company = models.ForeignKey("organizations.Company", on_delete=models.PROTECT, related_name="content_manifests")
    zone = models.ForeignKey("organizations.Zone", on_delete=models.PROTECT, related_name="content_manifests")
    version = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.GENERATING, db_index=True)
    generated_at = models.DateTimeField(db_index=True)
    valid_from = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    checksum = models.CharField(max_length=128)
    schedule_version = models.PositiveIntegerField(null=True, blank=True)
    policy_version = models.PositiveIntegerField(null=True, blank=True)
    total_size_bytes = models.PositiveBigIntegerField(default=0)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["zone", "version"], name="uniq_manifest_zone_version"),
        ]
        indexes = [
            models.Index(fields=["company", "status"]),
            models.Index(fields=["zone", "version"]),
            models.Index(fields=["created_at"]),
        ]

    def clean(self):
        super().clean()
        if self.zone.company_id != self.company_id:
            raise ValidationError({"zone": "La zona debe pertenecer a la misma empresa."})


class ContentManifestItem(UUIDModel):
    class Reason(models.TextChoices):
        SCHEDULE = "SCHEDULE", "Schedule"
        CHANNEL = "CHANNEL", "Channel"
        PLAYLIST = "PLAYLIST", "Playlist"
        CAMPAIGN = "CAMPAIGN", "Campaign"
        FALLBACK = "FALLBACK", "Fallback"

    manifest = models.ForeignKey(ContentManifest, on_delete=models.PROTECT, related_name="items")
    audio_asset = models.ForeignKey("catalog.AudioAsset", on_delete=models.PROTECT, related_name="manifest_items")
    priority = models.IntegerField(default=0)
    is_required = models.BooleanField(default=True)
    reason = models.CharField(max_length=20, choices=Reason.choices)
    checksum_sha256 = models.CharField(max_length=64)
    size_bytes = models.PositiveBigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["manifest", "audio_asset"], name="uniq_manifest_audio_asset"),
        ]


class PlaybackSession(UUIDModel):
    class Mode(models.TextChoices):
        ONLINE = "ONLINE", "Online"
        OFFLINE = "OFFLINE", "Offline"

    company = models.ForeignKey("organizations.Company", on_delete=models.PROTECT, related_name="playback_sessions")
    zone = models.ForeignKey("organizations.Zone", on_delete=models.PROTECT, related_name="playback_sessions")
    device = models.ForeignKey("devices.Device", on_delete=models.PROTECT, related_name="playback_sessions")
    started_at = models.DateTimeField(db_index=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    mode = models.CharField(max_length=20, choices=Mode.choices)
    manifest = models.ForeignKey(ContentManifest, on_delete=models.SET_NULL, null=True, blank=True, related_name="playback_sessions")
    app_version = models.CharField(max_length=120, blank=True)
    close_reason = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["company", "started_at"]),
            models.Index(fields=["zone", "started_at"]),
        ]

    def clean(self):
        super().clean()
        if self.zone.company_id != self.company_id:
            raise ValidationError({"zone": "La zona debe pertenecer a la misma empresa."})
        if self.device.company_id != self.company_id:
            raise ValidationError({"device": "El dispositivo debe pertenecer a la misma empresa."})


class PlaybackEvent(UUIDModel):
    class Outcome(models.TextChoices):
        COMPLETED = "COMPLETED", "Completed"
        SKIPPED = "SKIPPED", "Skipped"
        INTERRUPTED = "INTERRUPTED", "Interrupted"
        ERROR = "ERROR", "Error"

    class Source(models.TextChoices):
        SCHEDULE = "SCHEDULE", "Schedule"
        MANUAL = "MANUAL", "Manual"
        CAMPAIGN = "CAMPAIGN", "Campaign"
        FALLBACK = "FALLBACK", "Fallback"
        OFFLINE_RECOVERY = "OFFLINE_RECOVERY", "Offline recovery"

    company = models.ForeignKey("organizations.Company", on_delete=models.PROTECT, related_name="playback_events")
    session = models.ForeignKey(PlaybackSession, on_delete=models.PROTECT, related_name="events")
    audio_content = models.ForeignKey("catalog.AudioContent", on_delete=models.PROTECT, related_name="playback_events")
    audio_asset = models.ForeignKey("catalog.AudioAsset", on_delete=models.SET_NULL, null=True, blank=True, related_name="playback_events")
    channel = models.ForeignKey("playlists.Channel", on_delete=models.SET_NULL, null=True, blank=True, related_name="playback_events")
    playlist = models.ForeignKey("playlists.Playlist", on_delete=models.SET_NULL, null=True, blank=True, related_name="playback_events")
    campaign = models.ForeignKey("campaigns.Campaign", on_delete=models.SET_NULL, null=True, blank=True, related_name="playback_events")
    schedule_block = models.ForeignKey("scheduling.ScheduleBlock", on_delete=models.SET_NULL, null=True, blank=True, related_name="playback_events")
    started_at = models.DateTimeField(db_index=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    planned_duration_ms = models.PositiveBigIntegerField(null=True, blank=True)
    played_duration_ms = models.PositiveBigIntegerField(null=True, blank=True)
    outcome = models.CharField(max_length=20, choices=Outcome.choices)
    source = models.CharField(max_length=30, choices=Source.choices)
    error_code = models.CharField(max_length=80, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["company", "started_at"]),
            models.Index(fields=["session", "started_at"]),
            models.Index(fields=["audio_content", "started_at"]),
            models.Index(fields=["campaign", "started_at"]),
        ]

    def clean(self):
        super().clean()
        if self.session.company_id != self.company_id:
            raise ValidationError({"session": "La sesion debe pertenecer a la misma empresa."})
