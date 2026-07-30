from django.core.exceptions import ValidationError
from django.db import models

from shared.db.models import TimeStampedUUIDModel, UUIDModel


class Genre(TimeStampedUUIDModel):
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True)
    description = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        indexes = [
            models.Index(fields=["is_active", "sort_order"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["updated_at"]),
        ]


class TagCategory(TimeStampedUUIDModel):
    code = models.CharField(max_length=80, unique=True)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)


class Tag(TimeStampedUUIDModel):
    category = models.ForeignKey(TagCategory, on_delete=models.PROTECT, related_name="tags")
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140)
    description = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["category", "slug"], name="uniq_tag_category_slug"),
        ]
        indexes = [
            models.Index(fields=["category", "is_active"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["updated_at"]),
        ]


class AudioContent(TimeStampedUUIDModel):
    class ContentType(models.TextChoices):
        SONG = "SONG", "Song"
        MESSAGE = "MESSAGE", "Message"

    class Visibility(models.TextChoices):
        GLOBAL = "GLOBAL", "Global"
        PRIVATE = "PRIVATE", "Private"
        SHARED = "SHARED", "Shared"

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PROCESSING = "PROCESSING", "Processing"
        READY = "READY", "Ready"
        DISABLED = "DISABLED", "Disabled"
        ERROR = "ERROR", "Error"
        ARCHIVED = "ARCHIVED", "Archived"

    owner_company = models.ForeignKey("organizations.Company", on_delete=models.PROTECT, null=True, blank=True, related_name="audio_contents")
    content_type = models.CharField(max_length=20, choices=ContentType.choices, db_index=True)
    title = models.CharField(max_length=255)
    internal_code = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    visibility = models.CharField(max_length=20, choices=Visibility.choices, default=Visibility.GLOBAL)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)
    duration_ms = models.PositiveBigIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="created_audio_contents")
    published_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["owner_company", "internal_code"], name="uniq_owner_audio_internal_code"),
            models.UniqueConstraint(fields=["internal_code"], condition=models.Q(owner_company__isnull=True), name="uniq_global_audio_internal_code"),
        ]
        indexes = [
            models.Index(fields=["owner_company", "status"]),
            models.Index(fields=["content_type", "status"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["updated_at"]),
        ]


class Song(TimeStampedUUIDModel):
    audio_content = models.OneToOneField(AudioContent, on_delete=models.PROTECT, related_name="song")
    genre = models.ForeignKey(Genre, on_delete=models.PROTECT, related_name="songs")
    ai_generated = models.BooleanField(default=True)
    generation_provider = models.CharField(max_length=120, blank=True)
    generation_model = models.CharField(max_length=120, blank=True)
    generation_reference = models.CharField(max_length=255, blank=True)
    is_explicit = models.BooleanField(default=False)
    internal_notes = models.TextField(blank=True)

    def clean(self):
        super().clean()
        if self.audio_content_id and self.audio_content.content_type != AudioContent.ContentType.SONG:
            raise ValidationError({"audio_content": "El contenido debe ser de tipo SONG."})


class SongTag(UUIDModel):
    class Source(models.TextChoices):
        MANUAL = "MANUAL", "Manual"
        AUTOMATIC = "AUTOMATIC", "Automatic"

    song = models.ForeignKey(Song, on_delete=models.PROTECT, related_name="song_tags")
    tag = models.ForeignKey(Tag, on_delete=models.PROTECT, related_name="song_tags")
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.MANUAL)
    confidence = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    created_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="created_song_tags")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["song", "tag"], name="uniq_song_tag"),
            models.CheckConstraint(
                name="song_tag_confidence_when_auto",
                check=models.Q(source="AUTOMATIC") | models.Q(confidence__isnull=True),
            ),
        ]


class AudioMessage(TimeStampedUUIDModel):
    class MessageType(models.TextChoices):
        CORPORATE = "CORPORATE", "Corporate"
        PROMOTION = "PROMOTION", "Promotion"
        INFORMATIONAL = "INFORMATIONAL", "Informational"
        ALERT = "ALERT", "Alert"
        OTHER = "OTHER", "Other"

    audio_content = models.OneToOneField(AudioContent, on_delete=models.PROTECT, related_name="audio_message")
    message_type = models.CharField(max_length=20, choices=MessageType.choices)
    default_priority = models.IntegerField(default=0)
    is_skippable = models.BooleanField(default=True)
    internal_notes = models.TextField(blank=True)

    def clean(self):
        super().clean()
        if self.audio_content_id and self.audio_content.content_type != AudioContent.ContentType.MESSAGE:
            raise ValidationError({"audio_content": "El contenido debe ser de tipo MESSAGE."})


class AudioAsset(TimeStampedUUIDModel):
    class AssetRole(models.TextChoices):
        ORIGINAL = "ORIGINAL", "Original"
        NORMALIZED = "NORMALIZED", "Normalized"
        STREAM = "STREAM", "Stream"
        OFFLINE = "OFFLINE", "Offline"
        PREVIEW = "PREVIEW", "Preview"

    class ProcessingStatus(models.TextChoices):
        UPLOADED = "UPLOADED", "Uploaded"
        PENDING = "PENDING", "Pending"
        PROCESSING = "PROCESSING", "Processing"
        READY = "READY", "Ready"
        ERROR = "ERROR", "Error"
        ARCHIVED = "ARCHIVED", "Archived"

    audio_content = models.ForeignKey(AudioContent, on_delete=models.PROTECT, related_name="assets")
    asset_role = models.CharField(max_length=20, choices=AssetRole.choices)
    storage_backend = models.CharField(max_length=80)
    storage_key = models.CharField(max_length=512)
    original_filename = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=120)
    container_format = models.CharField(max_length=50)
    codec = models.CharField(max_length=50)
    bitrate_kbps = models.PositiveIntegerField(null=True, blank=True)
    sample_rate_hz = models.PositiveIntegerField(null=True, blank=True)
    channels = models.PositiveSmallIntegerField(null=True, blank=True)
    size_bytes = models.PositiveBigIntegerField()
    duration_ms = models.PositiveBigIntegerField(null=True, blank=True)
    checksum_sha256 = models.CharField(max_length=64)
    version = models.PositiveIntegerField()
    processing_status = models.CharField(max_length=20, choices=ProcessingStatus.choices, default=ProcessingStatus.UPLOADED)
    is_primary = models.BooleanField(default=False)
    created_from_asset = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="derived_assets")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["audio_content", "version", "asset_role"], name="uniq_audio_asset_content_version_role"),
            models.UniqueConstraint(fields=["storage_backend", "storage_key"], name="uniq_audio_asset_storage_key"),
            models.UniqueConstraint(fields=["audio_content"], condition=models.Q(is_primary=True, processing_status="READY"), name="uniq_primary_ready_asset_per_content"),
        ]
        indexes = [
            models.Index(fields=["audio_content", "processing_status"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["updated_at"]),
        ]


class AudioAnalysis(TimeStampedUUIDModel):
    audio_asset = models.OneToOneField(AudioAsset, on_delete=models.PROTECT, related_name="analysis")
    integrated_lufs = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    true_peak_db = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    loudness_range = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    peak_db = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    silence_start_ms = models.PositiveIntegerField(null=True, blank=True)
    silence_end_ms = models.PositiveIntegerField(null=True, blank=True)
    detected_bpm = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    detected_key = models.CharField(max_length=20, blank=True)
    analysis_version = models.CharField(max_length=80)
    raw_data = models.JSONField(default=dict, blank=True)


class UploadSession(UUIDModel):
    class TargetContentType(models.TextChoices):
        SONG = "SONG", "Song"
        MESSAGE = "MESSAGE", "Message"

    class Status(models.TextChoices):
        CREATED = "CREATED", "Created"
        UPLOADING = "UPLOADING", "Uploading"
        UPLOADED = "UPLOADED", "Uploaded"
        PROCESSING = "PROCESSING", "Processing"
        COMPLETED = "COMPLETED", "Completed"
        ERROR = "ERROR", "Error"
        CANCELLED = "CANCELLED", "Cancelled"

    uploaded_by = models.ForeignKey("users.User", on_delete=models.PROTECT, related_name="upload_sessions")
    owner_company = models.ForeignKey("organizations.Company", on_delete=models.PROTECT, null=True, blank=True, related_name="upload_sessions")
    original_filename = models.CharField(max_length=255)
    storage_key = models.CharField(max_length=512)
    size_bytes = models.PositiveBigIntegerField()
    checksum_sha256 = models.CharField(max_length=64)
    target_content_type = models.CharField(max_length=20, choices=TargetContentType.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.CREATED, db_index=True)
    created_audio_content = models.ForeignKey(AudioContent, on_delete=models.SET_NULL, null=True, blank=True, related_name="upload_sessions")
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)


class ProcessingJob(TimeStampedUUIDModel):
    class JobType(models.TextChoices):
        VALIDATE = "VALIDATE", "Validate"
        PROBE = "PROBE", "Probe"
        ANALYZE = "ANALYZE", "Analyze"
        NORMALIZE = "NORMALIZE", "Normalize"
        TRANSCODE = "TRANSCODE", "Transcode"
        GENERATE_PREVIEW = "GENERATE_PREVIEW", "Generate preview"
        CHECKSUM = "CHECKSUM", "Checksum"

    class Status(models.TextChoices):
        QUEUED = "QUEUED", "Queued"
        RUNNING = "RUNNING", "Running"
        SUCCEEDED = "SUCCEEDED", "Succeeded"
        FAILED = "FAILED", "Failed"
        CANCELLED = "CANCELLED", "Cancelled"

    audio_asset = models.ForeignKey(AudioAsset, on_delete=models.PROTECT, related_name="processing_jobs")
    job_type = models.CharField(max_length=30, choices=JobType.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED, db_index=True)
    progress = models.PositiveSmallIntegerField(default=0)
    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=3)
    queued_at = models.DateTimeField(db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    error_code = models.CharField(max_length=80, blank=True)
    error_message = models.TextField(blank=True)
    parameters = models.JSONField(default=dict, blank=True)
    result = models.JSONField(default=dict, blank=True)
