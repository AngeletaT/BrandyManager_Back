from django.core.exceptions import ValidationError
from django.db import models

from shared.db.models import TimeStampedUUIDModel, validate_date_range


class Schedule(TimeStampedUUIDModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PUBLISHED = "PUBLISHED", "Published"
        DISABLED = "DISABLED", "Disabled"
        ARCHIVED = "ARCHIVED", "Archived"

    company = models.ForeignKey("organizations.Company", on_delete=models.PROTECT, related_name="schedules")
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    timezone = models.CharField(max_length=64)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)
    valid_from = models.DateField(null=True, blank=True)
    valid_until = models.DateField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="created_schedules")
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["company", "status"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["updated_at"]),
        ]


class ScheduleBlock(TimeStampedUUIDModel):
    class ContentType(models.TextChoices):
        CHANNEL = "CHANNEL", "Channel"
        PLAYLIST = "PLAYLIST", "Playlist"
        SILENCE = "SILENCE", "Silence"

    schedule = models.ForeignKey(Schedule, on_delete=models.PROTECT, related_name="blocks")
    day_of_week = models.PositiveSmallIntegerField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    content_type = models.CharField(max_length=20, choices=ContentType.choices)
    channel = models.ForeignKey("playlists.Channel", on_delete=models.PROTECT, null=True, blank=True, related_name="schedule_blocks")
    playlist = models.ForeignKey("playlists.Playlist", on_delete=models.PROTECT, null=True, blank=True, related_name="schedule_blocks")
    priority = models.IntegerField(default=0)
    volume_override = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(name="schedule_block_day_range", check=models.Q(day_of_week__gte=0, day_of_week__lte=6)),
            models.CheckConstraint(name="schedule_block_volume_range", check=models.Q(volume_override__isnull=True) | models.Q(volume_override__gte=0, volume_override__lte=100)),
            models.CheckConstraint(
                name="schedule_block_content_target",
                check=(
                    models.Q(content_type="CHANNEL", channel__isnull=False, playlist__isnull=True)
                    | models.Q(content_type="PLAYLIST", channel__isnull=True, playlist__isnull=False)
                    | models.Q(content_type="SILENCE", channel__isnull=True, playlist__isnull=True)
                ),
            ),
        ]
        indexes = [
            models.Index(fields=["schedule", "day_of_week", "start_time"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["updated_at"]),
        ]

    def clean(self):
        super().clean()
        if self.start_time >= self.end_time:
            raise ValidationError({"end_time": "Los bloques que cruzan medianoche deben dividirse en dos registros."})


class ScheduleException(TimeStampedUUIDModel):
    class Action(models.TextChoices):
        REPLACE = "REPLACE", "Replace"
        SILENCE = "SILENCE", "Silence"
        VOLUME_OVERRIDE = "VOLUME_OVERRIDE", "Volume override"

    schedule = models.ForeignKey(Schedule, on_delete=models.PROTECT, related_name="exceptions")
    date = models.DateField(db_index=True)
    start_time = models.TimeField()
    end_time = models.TimeField()
    action = models.CharField(max_length=20, choices=Action.choices)
    channel = models.ForeignKey("playlists.Channel", on_delete=models.PROTECT, null=True, blank=True, related_name="schedule_exceptions")
    playlist = models.ForeignKey("playlists.Playlist", on_delete=models.PROTECT, null=True, blank=True, related_name="schedule_exceptions")
    priority = models.IntegerField(default=0)
    volume_override = models.PositiveSmallIntegerField(null=True, blank=True)
    description = models.TextField(blank=True)


class ScheduleAssignment(TimeStampedUUIDModel):
    company = models.ForeignKey("organizations.Company", on_delete=models.PROTECT, related_name="schedule_assignments")
    schedule = models.ForeignKey(Schedule, on_delete=models.PROTECT, related_name="assignments")
    scope = models.ForeignKey("organizations.ResourceScope", on_delete=models.PROTECT, related_name="schedule_assignments")
    priority = models.IntegerField(default=0, db_index=True)
    is_locked = models.BooleanField(default=False)
    starts_at = models.DateTimeField(null=True, blank=True, db_index=True)
    ends_at = models.DateTimeField(null=True, blank=True, db_index=True)
    assigned_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_schedules")
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["company", "is_active", "priority"]),
            models.Index(fields=["scope", "is_active"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["updated_at"]),
        ]

    def clean(self):
        super().clean()
        validate_date_range(starts_at=self.starts_at, ends_at=self.ends_at)
        if self.schedule.company_id != self.company_id:
            raise ValidationError({"schedule": "La programacion debe pertenecer a la misma empresa."})
        if self.scope.company_id != self.company_id:
            raise ValidationError({"scope": "El ambito debe pertenecer a la misma empresa."})
