import uuid

from django.core.exceptions import ValidationError
from django.db import models

from shared.db.models import TimeStampedUUIDModel


class Campaign(TimeStampedUUIDModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PENDING_APPROVAL = "PENDING_APPROVAL", "Pending approval"
        APPROVED = "APPROVED", "Approved"
        ACTIVE = "ACTIVE", "Active"
        PAUSED = "PAUSED", "Paused"
        FINISHED = "FINISHED", "Finished"
        CANCELLED = "CANCELLED", "Cancelled"

    company = models.ForeignKey("organizations.Company", on_delete=models.PROTECT, related_name="campaigns")
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.DRAFT, db_index=True)
    starts_at = models.DateTimeField(db_index=True)
    ends_at = models.DateTimeField(db_index=True)
    timezone = models.CharField(max_length=64)
    priority = models.IntegerField(default=0)
    created_by = models.ForeignKey("users.User", on_delete=models.PROTECT, related_name="created_campaigns")
    approved_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="approved_campaigns")
    approved_at = models.DateTimeField(null=True, blank=True)

    def clean(self):
        super().clean()
        if self.ends_at <= self.starts_at:
            raise ValidationError({"ends_at": "Debe ser posterior a starts_at."})


class CampaignMessage(TimeStampedUUIDModel):
    campaign = models.ForeignKey(Campaign, on_delete=models.PROTECT, related_name="messages")
    audio_message = models.ForeignKey("catalog.AudioMessage", on_delete=models.PROTECT, related_name="campaign_messages")
    position = models.PositiveIntegerField()
    weight = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)


class CampaignRule(TimeStampedUUIDModel):
    class RuleType(models.TextChoices):
        SONG_COUNT = "SONG_COUNT", "Song count"
        MINUTES = "MINUTES", "Minutes"
        FIXED_TIME = "FIXED_TIME", "Fixed time"
        MANUAL = "MANUAL", "Manual"

    campaign = models.ForeignKey(Campaign, on_delete=models.PROTECT, related_name="rules")
    rule_type = models.CharField(max_length=20, choices=RuleType.choices)
    interval_song_count = models.PositiveIntegerField(null=True, blank=True)
    interval_minutes = models.PositiveIntegerField(null=True, blank=True)
    max_plays_per_day = models.PositiveIntegerField(null=True, blank=True)
    minimum_gap_minutes = models.PositiveIntegerField(null=True, blank=True)
    settings = models.JSONField(default=dict, blank=True)

    def clean(self):
        super().clean()
        if self.rule_type == self.RuleType.SONG_COUNT and not self.interval_song_count:
            raise ValidationError({"interval_song_count": "SONG_COUNT necesita interval_song_count."})
        if self.rule_type == self.RuleType.MINUTES and not self.interval_minutes:
            raise ValidationError({"interval_minutes": "MINUTES necesita interval_minutes."})


class CampaignRuleTime(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    rule = models.ForeignKey(CampaignRule, on_delete=models.PROTECT, related_name="times")
    day_of_week = models.PositiveSmallIntegerField(null=True, blank=True)
    time = models.TimeField()
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)


class CampaignTarget(TimeStampedUUIDModel):
    company = models.ForeignKey("organizations.Company", on_delete=models.PROTECT, related_name="campaign_targets")
    campaign = models.ForeignKey(Campaign, on_delete=models.PROTECT, related_name="targets")
    scope = models.ForeignKey("organizations.ResourceScope", on_delete=models.PROTECT, related_name="campaign_targets")
    priority = models.IntegerField(default=0)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    assigned_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_campaign_targets")

    def clean(self):
        super().clean()
        if self.campaign.company_id != self.company_id:
            raise ValidationError({"campaign": "La campana debe pertenecer a la misma empresa."})
        if self.scope.company_id != self.company_id:
            raise ValidationError({"scope": "El ambito debe pertenecer a la misma empresa."})
