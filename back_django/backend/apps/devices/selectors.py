from datetime import timedelta

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from apps.authorization.services import get_or_create_zone_scope, zone_ids_accessible_by_membership
from apps.devices.models import Device


def list_devices_for_membership(
    *,
    membership,
    search="",
    administrative_status="",
    activation_status="",
    connectivity_status="",
    site_id=None,
    zone_id=None,
):
    zone_ids = zone_ids_accessible_by_membership(membership=membership, permission_code="devices.view")
    queryset = (
        Device.objects.filter(company=membership.company)
        .select_related(
            "zone",
            "zone__site",
            "state",
            "state__current_audio_content",
            "state__current_channel",
            "state__current_playlist",
        )
        .order_by("name", "code")
    )
    if zone_ids is not None:
        queryset = queryset.filter(zone_id__in=zone_ids)
    if zone_id:
        queryset = queryset.filter(zone_id=zone_id)
    if site_id:
        queryset = queryset.filter(zone__site_id=site_id)
    if search:
        queryset = queryset.filter(Q(name__icontains=search) | Q(code__icontains=search))
    if administrative_status:
        queryset = queryset.filter(administrative_status=administrative_status)
    if activation_status:
        queryset = queryset.filter(activation_status=activation_status)
    if connectivity_status:
        threshold = timezone.now() - timedelta(seconds=settings.BM_DEVICE_OFFLINE_THRESHOLD_SECONDS)
        if connectivity_status == Device.ConnectivityStatus.ONLINE:
            queryset = queryset.filter(last_seen_at__gte=threshold)
        elif connectivity_status == Device.ConnectivityStatus.OFFLINE:
            queryset = queryset.filter(last_seen_at__isnull=False, last_seen_at__lt=threshold)
        else:
            queryset = queryset.filter(last_seen_at__isnull=True)
    return queryset


def get_device_for_membership(*, membership, device_id):
    return list_devices_for_membership(membership=membership).filter(id=device_id).first()


def get_device_scope(*, device):
    return get_or_create_zone_scope(zone=device.zone)


def list_device_commands(*, device):
    return device.commands.order_by("-created_at", "-id")


def list_device_events(*, device):
    return device.events.select_related("audio_asset", "manifest").order_by("-occurred_at", "-id")
