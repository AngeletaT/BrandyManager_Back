from django.db.models import Q
from django.utils import timezone

from apps.organizations.models import MembershipGrant


def membership_has_active_role(*, membership, role_code, at=None):
    at = at or timezone.now()
    return MembershipGrant.objects.filter(
        membership=membership,
        role__code=role_code,
        is_active=True,
    ).filter(
        Q(starts_at__isnull=True) | Q(starts_at__lte=at),
        Q(ends_at__isnull=True) | Q(ends_at__gt=at),
    ).exists()
