import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from shared.db.models import TimeStampedUUIDModel, UUIDModel


class Device(TimeStampedUUIDModel):
    class DeviceType(models.TextChoices):
        DEDICATED_PLAYER = "DEDICATED_PLAYER", "Dedicated player"
        DESKTOP_APP = "DESKTOP_APP", "Desktop app"
        MOBILE_APP = "MOBILE_APP", "Mobile app"
        OTHER = "OTHER", "Other"

    class Status(models.TextChoices):
        PROVISIONING = "PROVISIONING", "Provisioning"
        ONLINE = "ONLINE", "Online"
        OFFLINE = "OFFLINE", "Offline"
        MAINTENANCE = "MAINTENANCE", "Maintenance"
        DISABLED = "DISABLED", "Disabled"
        REVOKED = "REVOKED", "Revoked"

    class AdministrativeStatus(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        SUSPENDED = "SUSPENDED", "Suspended"
        ARCHIVED = "ARCHIVED", "Archived"

    class ActivationStatus(models.TextChoices):
        PENDING = "PENDING", "Pending"
        ACTIVATED = "ACTIVATED", "Activated"
        REVOKED = "REVOKED", "Revoked"

    class ConnectivityStatus(models.TextChoices):
        UNKNOWN = "UNKNOWN", "Unknown"
        ONLINE = "ONLINE", "Online"
        OFFLINE = "OFFLINE", "Offline"

    company = models.ForeignKey("organizations.Company", on_delete=models.PROTECT, related_name="devices")
    zone = models.ForeignKey(
        "organizations.Zone",
        on_delete=models.PROTECT,
        related_name="devices",
        null=True,
        blank=True,
    )
    hardware_id = models.CharField(max_length=255, unique=True)
    code = models.CharField(max_length=80)
    name = models.CharField(max_length=255)
    device_type = models.CharField(max_length=30, choices=DeviceType.choices)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.PROVISIONING, db_index=True)
    administrative_status = models.CharField(
        max_length=20,
        choices=AdministrativeStatus.choices,
        default=AdministrativeStatus.ACTIVE,
        db_index=True,
    )
    activation_status = models.CharField(
        max_length=20,
        choices=ActivationStatus.choices,
        default=ActivationStatus.PENDING,
        db_index=True,
    )
    connectivity_status = models.CharField(
        max_length=20,
        choices=ConnectivityStatus.choices,
        default=ConnectivityStatus.UNKNOWN,
        db_index=True,
    )
    configuration = models.JSONField(default=dict, blank=True)
    configuration_version = models.PositiveIntegerField(default=1)
    os_name = models.CharField(max_length=120, blank=True)
    os_version = models.CharField(max_length=120, blank=True)
    app_version = models.CharField(max_length=120, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    mac_address = models.CharField(max_length=32, blank=True)
    storage_total_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    storage_free_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    deactivated_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["company", "code"], name="uniq_device_company_code"),
        ]
        indexes = [
            models.Index(fields=["company", "status"]),
            models.Index(fields=["company", "administrative_status"]),
            models.Index(fields=["company", "activation_status"]),
            models.Index(fields=["zone", "administrative_status"]),
            models.Index(fields=["last_seen_at"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["updated_at"]),
        ]

    def clean(self):
        super().clean()
        if self.zone_id and self.zone.company_id != self.company_id:
            raise ValidationError({"zone": "La zona debe pertenecer a la misma empresa."})


class DeviceZoneAssignment(UUIDModel):
    class AssignmentRole(models.TextChoices):
        PRIMARY = "PRIMARY", "Primary"
        STANDBY = "STANDBY", "Standby"

    company = models.ForeignKey("organizations.Company", on_delete=models.PROTECT, related_name="device_zone_assignments")
    device = models.ForeignKey(Device, on_delete=models.PROTECT, related_name="zone_assignments")
    zone = models.ForeignKey("organizations.Zone", on_delete=models.PROTECT, related_name="device_assignments")
    assignment_role = models.CharField(max_length=20, choices=AssignmentRole.choices, default=AssignmentRole.PRIMARY)
    assigned_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_devices")
    assigned_at = models.DateTimeField(db_index=True)
    unassigned_at = models.DateTimeField(null=True, blank=True, db_index=True)
    unassigned_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="unassigned_devices")
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["device"], condition=models.Q(unassigned_at__isnull=True), name="uniq_active_assignment_per_device"),
        ]
        indexes = [
            models.Index(fields=["company", "assigned_at"]),
            models.Index(fields=["zone", "unassigned_at"]),
        ]

    def clean(self):
        super().clean()
        if self.device.company_id != self.company_id:
            raise ValidationError({"device": "El dispositivo debe pertenecer a la misma empresa."})
        if self.zone.company_id != self.company_id:
            raise ValidationError({"zone": "La zona debe pertenecer a la misma empresa."})


class DeviceActivation(TimeStampedUUIDModel):
    device = models.ForeignKey(Device, on_delete=models.PROTECT, related_name="activation_codes")
    code_hash = models.CharField(max_length=64, unique=True, db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=5)
    consumed_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    last_attempt_ip = models.GenericIPAddressField(null=True, blank=True)
    created_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_device_activations",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["device"],
                condition=models.Q(consumed_at__isnull=True, revoked_at__isnull=True),
                name="uniq_active_device_activation_per_device",
            ),
        ]
        indexes = [
            models.Index(fields=["device", "expires_at"]),
            models.Index(fields=["created_at"]),
        ]

    def is_active(self, *, at):
        return (
            self.consumed_at is None
            and self.revoked_at is None
            and self.expires_at > at
            and self.attempts < self.max_attempts
        )


class DeviceCredential(UUIDModel):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        EXPIRED = "EXPIRED", "Expired"
        REVOKED = "REVOKED", "Revoked"

    device = models.ForeignKey(Device, on_delete=models.PROTECT, related_name="credentials")
    credential_id = models.CharField(max_length=255, unique=True)
    secret_hash = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    rotated_from = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="rotated_to")

    class Meta:
        indexes = [
            models.Index(fields=["device", "status"]),
            models.Index(fields=["expires_at"]),
        ]


class DeviceCommand(UUIDModel):
    class CommandType(models.TextChoices):
        SET_VOLUME = "SET_VOLUME", "Set volume"
        MUTE = "MUTE", "Mute"
        UNMUTE = "UNMUTE", "Unmute"
        RESTART_PLAYBACK = "RESTART_PLAYBACK", "Restart playback"
        FORCE_SYNC = "FORCE_SYNC", "Force sync"
        ENABLE = "ENABLE", "Enable"
        DISABLE = "DISABLE", "Disable"
        CHANGE_CHANNEL = "CHANGE_CHANNEL", "Change channel"
        PAUSE = "PAUSE", "Pause"
        RESUME = "RESUME", "Resume"
        SKIP = "SKIP", "Skip"
        SYNC = "SYNC", "Sync"
        RESTART = "RESTART", "Restart"
        UPDATE_APP = "UPDATE_APP", "Update app"
        REFRESH_CONFIGURATION = "REFRESH_CONFIGURATION", "Refresh configuration"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        DELIVERED = "DELIVERED", "Delivered"
        ACKNOWLEDGED = "ACKNOWLEDGED", "Acknowledged"
        EXECUTED = "EXECUTED", "Executed"
        FAILED = "FAILED", "Failed"
        EXPIRED = "EXPIRED", "Expired"
        CANCELLED = "CANCELLED", "Cancelled"

    company = models.ForeignKey("organizations.Company", on_delete=models.PROTECT, related_name="device_commands")
    device = models.ForeignKey(Device, on_delete=models.PROTECT, related_name="commands")
    command_type = models.CharField(max_length=40, choices=CommandType.choices)
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    created_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="created_device_commands")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    executed_at = models.DateTimeField(null=True, blank=True)
    result = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    idempotency_key = models.UUIDField(null=True, blank=True, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["company", "idempotency_key"],
                condition=models.Q(idempotency_key__isnull=False),
                name="uniq_device_command_idempotency_key",
            ),
        ]
        indexes = [
            models.Index(fields=["device", "status"]),
            models.Index(fields=["company", "created_at"]),
        ]

    def clean(self):
        super().clean()
        if self.device.company_id != self.company_id:
            raise ValidationError({"device": "El dispositivo debe pertenecer a la misma empresa."})


class DeviceEvent(UUIDModel):
    class Severity(models.TextChoices):
        DEBUG = "DEBUG", "Debug"
        INFO = "INFO", "Info"
        WARNING = "WARNING", "Warning"
        ERROR = "ERROR", "Error"
        CRITICAL = "CRITICAL", "Critical"

    company = models.ForeignKey("organizations.Company", on_delete=models.PROTECT, related_name="device_events")
    device = models.ForeignKey(Device, on_delete=models.PROTECT, related_name="events")
    external_event_id = models.UUIDField(null=True, blank=True)
    sequence = models.PositiveBigIntegerField(null=True, blank=True)
    event_type = models.CharField(max_length=120)
    severity = models.CharField(max_length=20, choices=Severity.choices, default=Severity.INFO)
    occurred_at = models.DateTimeField(db_index=True)
    received_at = models.DateTimeField(default=timezone.now, db_index=True)
    manifest = models.ForeignKey(
        "playback.ContentManifest",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="device_events",
    )
    configuration_version = models.PositiveIntegerField(null=True, blank=True)
    audio_asset = models.ForeignKey(
        "catalog.AudioAsset",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="device_events",
    )
    position_ms = models.PositiveBigIntegerField(null=True, blank=True)
    error_code = models.CharField(max_length=80, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    app_version = models.CharField(max_length=120, blank=True)
    request_id = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["device", "external_event_id"],
                condition=models.Q(external_event_id__isnull=False),
                name="uniq_device_external_event",
            ),
        ]
        indexes = [
            models.Index(fields=["device", "sequence"]),
            models.Index(fields=["company", "occurred_at"]),
        ]


class DeviceState(models.Model):
    class PlaybackStatus(models.TextChoices):
        STOPPED = "STOPPED", "Stopped"
        PLAYING = "PLAYING", "Playing"
        PAUSED = "PAUSED", "Paused"
        BUFFERING = "BUFFERING", "Buffering"
        ERROR = "ERROR", "Error"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device = models.OneToOneField(Device, on_delete=models.PROTECT, related_name="state")
    zone = models.ForeignKey("organizations.Zone", on_delete=models.SET_NULL, null=True, blank=True, related_name="device_states")
    current_audio_content = models.ForeignKey("catalog.AudioContent", on_delete=models.SET_NULL, null=True, blank=True, related_name="device_states")
    current_channel = models.ForeignKey("playlists.Channel", on_delete=models.SET_NULL, null=True, blank=True, related_name="device_states")
    current_playlist = models.ForeignKey("playlists.Playlist", on_delete=models.SET_NULL, null=True, blank=True, related_name="device_states")
    playback_status = models.CharField(max_length=20, choices=PlaybackStatus.choices, default=PlaybackStatus.STOPPED)
    position_ms = models.PositiveBigIntegerField(default=0)
    volume = models.PositiveSmallIntegerField(default=60)
    is_online = models.BooleanField(default=False)
    last_heartbeat_at = models.DateTimeField(null=True, blank=True)
    manifest_version = models.PositiveIntegerField(null=True, blank=True)
    schedule_version = models.PositiveIntegerField(null=True, blank=True)
    last_sequence = models.PositiveBigIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)


class DeviceSync(TimeStampedUUIDModel):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        DOWNLOADING = "DOWNLOADING", "Downloading"
        VERIFYING = "VERIFYING", "Verifying"
        COMPLETED = "COMPLETED", "Completed"
        PARTIAL = "PARTIAL", "Partial"
        FAILED = "FAILED", "Failed"
        CANCELLED = "CANCELLED", "Cancelled"

    company = models.ForeignKey("organizations.Company", on_delete=models.PROTECT, related_name="device_syncs")
    device = models.ForeignKey(Device, on_delete=models.PROTECT, related_name="syncs")
    manifest = models.ForeignKey("playback.ContentManifest", on_delete=models.PROTECT, related_name="device_syncs")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    progress_percent = models.PositiveSmallIntegerField(default=0)
    bytes_total = models.PositiveBigIntegerField(default=0)
    bytes_downloaded = models.PositiveBigIntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)

    def clean(self):
        super().clean()
        if self.device.company_id != self.company_id:
            raise ValidationError({"device": "El dispositivo debe pertenecer a la misma empresa."})
        if self.manifest.company_id != self.company_id:
            raise ValidationError({"manifest": "El manifiesto debe pertenecer a la misma empresa."})


class DeviceCachedAsset(TimeStampedUUIDModel):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        DOWNLOADED = "DOWNLOADED", "Downloaded"
        VERIFIED = "VERIFIED", "Verified"
        CORRUPTED = "CORRUPTED", "Corrupted"
        DELETED = "DELETED", "Deleted"

    device = models.ForeignKey(Device, on_delete=models.PROTECT, related_name="cached_assets")
    audio_asset = models.ForeignKey("catalog.AudioAsset", on_delete=models.PROTECT, related_name="device_caches")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    downloaded_at = models.DateTimeField(null=True, blank=True)
    last_verified_at = models.DateTimeField(null=True, blank=True)
    checksum_valid = models.BooleanField(default=False)
    size_bytes = models.PositiveBigIntegerField(default=0)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["device", "audio_asset"], name="uniq_device_cached_asset"),
        ]
