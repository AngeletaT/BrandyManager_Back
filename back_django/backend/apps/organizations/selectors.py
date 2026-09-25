from django.db.models import Count, Prefetch, Q
from django.utils import timezone

from apps.authorization.services import site_ids_accessible_by_membership, zone_ids_accessible_by_membership
from apps.organizations.models import CompanyInvitation, CompanyMembership, MembershipGrant, Site, Zone


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


def get_current_company_for_membership(*, membership):
    return membership.company


def list_sites_for_membership(*, membership, permission_code="sites.view", search="", status_value="", site_type=""):
    site_ids = site_ids_accessible_by_membership(membership=membership, permission_code=permission_code)
    queryset = Site.objects.filter(company=membership.company).select_related("company").order_by("name")
    if site_ids is None:
        scoped_queryset = queryset
    else:
        scoped_queryset = queryset.filter(id__in=site_ids)
    if search:
        scoped_queryset = scoped_queryset.filter(
            Q(name__icontains=search)
            | Q(code__icontains=search)
            | Q(city__icontains=search)
            | Q(province__icontains=search)
            | Q(address_line_1__icontains=search)
        )
    if status_value:
        scoped_queryset = scoped_queryset.filter(status=status_value)
    if site_type:
        scoped_queryset = scoped_queryset.filter(site_type=site_type)
    return scoped_queryset


def get_site_for_membership(*, membership, site_id, permission_code="sites.view"):
    return list_sites_for_membership(membership=membership, permission_code=permission_code).filter(id=site_id).first()


def list_zones_for_membership(*, membership, permission_code="zones.view", site_id=None, search="", status_value=""):
    from apps.organizations.models import ZoneChannelAssignment

    zone_ids = zone_ids_accessible_by_membership(membership=membership, permission_code=permission_code)
    queryset = (
        Zone.objects.filter(company=membership.company)
        .select_related("site", "company")
        .prefetch_related(
            Prefetch(
                "channel_assignments",
                queryset=ZoneChannelAssignment.objects.filter(unassigned_at__isnull=True).select_related("channel"),
                to_attr="active_channel_assignments",
            )
        )
        .annotate(active_device_count=Count("devices", filter=~Q(devices__administrative_status="ARCHIVED")))
        .order_by("site__name", "name")
    )
    if site_id:
        queryset = queryset.filter(site_id=site_id)
    if zone_ids is not None:
        queryset = queryset.filter(id__in=zone_ids)
    if search:
        queryset = queryset.filter(
            Q(name__icontains=search)
            | Q(code__icontains=search)
            | Q(description__icontains=search)
            | Q(site__name__icontains=search)
        )
    if status_value:
        queryset = queryset.filter(status=status_value)
    return queryset


def get_zone_for_membership(*, membership, zone_id, permission_code="zones.view"):
    return list_zones_for_membership(membership=membership, permission_code=permission_code).filter(id=zone_id).first()


def list_memberships_for_company(*, company):
    return (
        CompanyMembership.objects.filter(
            company=company,
            status__in=[CompanyMembership.Status.ACTIVE, CompanyMembership.Status.SUSPENDED],
        )
        .select_related("user")
        .prefetch_related("grants__role", "grants__scope", "grants__scope__site", "grants__scope__zone")
        .order_by("user__email")
    )


def get_membership_for_company(*, company, membership_id):
    return list_memberships_for_company(company=company).filter(id=membership_id).first()


def list_invitations_for_company(*, company):
    return (
        CompanyInvitation.objects.filter(company=company)
        .select_related("company", "role", "invited_by")
        .order_by("-created_at")
    )


def get_invitation_for_company(*, company, invitation_id):
    return list_invitations_for_company(company=company).filter(id=invitation_id).first()
