from django.utils import timezone

from apps.audit.models import AuditLog


def register_audit_log(
    *,
    action,
    entity_type,
    company=None,
    actor_user=None,
    actor_device=None,
    entity_id=None,
    entity_label="",
    before_data=None,
    after_data=None,
    ip_address=None,
    user_agent="",
    request_id="",
    occurred_at=None,
):
    return AuditLog.objects.create(
        company=company,
        actor_user=actor_user,
        actor_device=actor_device,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_label=entity_label,
        before_data=before_data or {},
        after_data=after_data or {},
        ip_address=ip_address,
        user_agent=user_agent,
        request_id=request_id,
        occurred_at=occurred_at or timezone.now(),
    )
