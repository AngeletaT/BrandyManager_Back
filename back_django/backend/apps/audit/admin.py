from django.contrib import admin

from apps.audit.models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    readonly_fields = [field.name for field in AuditLog._meta.fields]
    list_display = ("action", "entity_type", "entity_id", "company", "actor_user", "occurred_at")
    search_fields = ("action", "entity_type", "entity_label", "request_id")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
