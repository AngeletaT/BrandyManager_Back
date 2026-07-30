from django.core.exceptions import ValidationError
from django.db import models

from shared.db.models import UUIDModel


class AuditLog(UUIDModel):
    company = models.ForeignKey("organizations.Company", on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_logs")
    actor_user = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_logs")
    actor_device = models.ForeignKey("devices.Device", on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_logs")
    action = models.CharField(max_length=120)
    entity_type = models.CharField(max_length=120)
    entity_id = models.UUIDField(null=True, blank=True)
    entity_label = models.CharField(max_length=255, blank=True)
    before_data = models.JSONField(default=dict, blank=True)
    after_data = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    request_id = models.CharField(max_length=120, blank=True)
    occurred_at = models.DateTimeField(db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["company", "occurred_at"]),
            models.Index(fields=["actor_user", "occurred_at"]),
            models.Index(fields=["entity_type", "entity_id"]),
        ]

    def save(self, *args, **kwargs):
        if self.pk and AuditLog.objects.filter(pk=self.pk).exists():
            raise ValidationError("Los registros de auditoria son inmutables.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Los registros de auditoria no pueden eliminarse.")
