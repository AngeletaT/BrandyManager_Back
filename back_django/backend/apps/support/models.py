from django.db import models

from shared.db.models import TimeStampedUUIDModel, UUIDModel


class Incident(TimeStampedUUIDModel):
    class Severity(models.TextChoices):
        LOW = "LOW", "Low"
        MEDIUM = "MEDIUM", "Medium"
        HIGH = "HIGH", "High"
        CRITICAL = "CRITICAL", "Critical"

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        ACKNOWLEDGED = "ACKNOWLEDGED", "Acknowledged"
        INVESTIGATING = "INVESTIGATING", "Investigating"
        RESOLVED = "RESOLVED", "Resolved"
        DISMISSED = "DISMISSED", "Dismissed"

    class DetectedBy(models.TextChoices):
        SYSTEM = "SYSTEM", "System"
        USER = "USER", "User"
        DEVICE = "DEVICE", "Device"

    company = models.ForeignKey("organizations.Company", on_delete=models.PROTECT, related_name="incidents")
    site = models.ForeignKey("organizations.Site", on_delete=models.SET_NULL, null=True, blank=True, related_name="incidents")
    zone = models.ForeignKey("organizations.Zone", on_delete=models.SET_NULL, null=True, blank=True, related_name="incidents")
    device = models.ForeignKey("devices.Device", on_delete=models.SET_NULL, null=True, blank=True, related_name="incidents")
    incident_type = models.CharField(max_length=120)
    severity = models.CharField(max_length=20, choices=Severity.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN, db_index=True)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    detected_by = models.CharField(max_length=20, choices=DetectedBy.choices)
    detected_at = models.DateTimeField(db_index=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    assigned_to = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_incidents")
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["company", "status"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["updated_at"]),
        ]


class IncidentEvent(UUIDModel):
    class EventType(models.TextChoices):
        CREATED = "CREATED", "Created"
        COMMENT = "COMMENT", "Comment"
        STATUS_CHANGE = "STATUS_CHANGE", "Status change"
        ASSIGNMENT = "ASSIGNMENT", "Assignment"
        AUTOMATIC_UPDATE = "AUTOMATIC_UPDATE", "Automatic update"

    incident = models.ForeignKey(Incident, on_delete=models.PROTECT, related_name="events")
    actor_user = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="incident_events")
    event_type = models.CharField(max_length=30, choices=EventType.choices)
    message = models.TextField(blank=True)
    old_status = models.CharField(max_length=30, blank=True)
    new_status = models.CharField(max_length=30, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)


class Notification(UUIDModel):
    user = models.ForeignKey("users.User", on_delete=models.PROTECT, related_name="notifications")
    company = models.ForeignKey("organizations.Company", on_delete=models.SET_NULL, null=True, blank=True, related_name="notifications")
    incident = models.ForeignKey(Incident, on_delete=models.SET_NULL, null=True, blank=True, related_name="notifications")
    notification_type = models.CharField(max_length=120)
    title = models.CharField(max_length=255)
    body = models.TextField(blank=True)
    data = models.JSONField(default=dict, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
