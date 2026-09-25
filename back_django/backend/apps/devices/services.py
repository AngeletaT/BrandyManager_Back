import hashlib
import hmac
import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.billing.selectors import get_current_subscription_for_company
from apps.devices.exceptions import (
    DeviceActivationInvalid,
    DeviceCodeConflict,
    DeviceCredentialRevoked,
    DeviceLimitReached,
    DeviceRevisionConflict,
    DeviceSessionExpired,
    DeviceZoneInvalid,
    PlaybackCommandInvalid,
)
from apps.devices.models import Device, DeviceActivation, DeviceCommand, DeviceCredential, DeviceEvent, DeviceState, DeviceZoneAssignment
from apps.organizations.models import Company, Site, Zone


ACTIVATION_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _hmac(value):
    secret = settings.BM_DEVICE_TOKEN_HASH_SECRET.encode("utf-8")
    return hmac.new(secret, value.encode("utf-8"), hashlib.sha256).hexdigest()


def _normalize_activation_code(value):
    return "".join(str(value or "").upper().split()).replace("-", "")


def _format_activation_code(value):
    return "-".join(value[index : index + 4] for index in range(0, len(value), 4))


def _active_device_count(*, company):
    return Device.objects.filter(company=company).exclude(
        administrative_status=Device.AdministrativeStatus.ARCHIVED
    ).count()


def _enforce_device_limit(*, company):
    subscription = get_current_subscription_for_company(company=company)
    limit = subscription.effective_limits().get("devices") if subscription else None
    if limit is not None and _active_device_count(company=company) >= limit:
        raise DeviceLimitReached()


def _ensure_zone_is_assignable(*, zone, company):
    if zone.company_id != company.id:
        raise DeviceZoneInvalid()
    if zone.status == Zone.Status.ARCHIVED or zone.site.status == Site.Status.ARCHIVED:
        raise DeviceZoneInvalid(message="No se puede usar una zona archivada.")
    return zone


def _invalidate_device_credentials(*, device, at):
    DeviceCredential.objects.filter(device=device, status=DeviceCredential.Status.ACTIVE).update(
        status=DeviceCredential.Status.REVOKED,
        revoked_at=at,
    )


def _invalidate_activation_codes(*, device, at):
    DeviceActivation.objects.filter(
        device=device,
        consumed_at__isnull=True,
        revoked_at__isnull=True,
    ).update(revoked_at=at)


@transaction.atomic
def assign_device_to_zone(*, device, zone, assigned_by=None, assignment_role=DeviceZoneAssignment.AssignmentRole.PRIMARY, reason=""):
    device = Device.objects.select_for_update(of=("self",)).select_related("company").get(pk=device.pk)
    zone = Zone.objects.select_for_update(of=("self",)).select_related("site", "company").get(pk=zone.pk)
    _ensure_zone_is_assignable(zone=zone, company=device.company)
    now = timezone.now()
    DeviceZoneAssignment.objects.select_for_update().filter(device=device, unassigned_at__isnull=True).update(
        unassigned_at=now,
        unassigned_by=assigned_by,
    )
    assignment = DeviceZoneAssignment.objects.create(
        company=device.company,
        device=device,
        zone=zone,
        assignment_role=assignment_role,
        assigned_by=assigned_by,
        assigned_at=now,
        reason=reason,
    )
    Device.objects.filter(pk=device.pk).update(zone=zone, configuration_version=device.configuration_version + 1)
    DeviceState.objects.filter(device=device).update(zone=zone)
    return assignment


@transaction.atomic
def replace_zone_device(*, old_assignment, new_device, assigned_by=None, reason=""):
    old_assignment = DeviceZoneAssignment.objects.select_for_update().select_related("zone").get(id=old_assignment.id)
    old_assignment.unassigned_at = timezone.now()
    old_assignment.unassigned_by = assigned_by
    old_assignment.reason = reason or old_assignment.reason
    old_assignment.save(update_fields=["unassigned_at", "unassigned_by", "reason"])
    return assign_device_to_zone(
        device=new_device,
        zone=old_assignment.zone,
        assigned_by=assigned_by,
        assignment_role=old_assignment.assignment_role,
        reason=reason,
    )


@transaction.atomic
def create_device(*, company, data, actor):
    company = Company.objects.select_for_update().get(pk=company.pk)
    _enforce_device_limit(company=company)
    zone = Zone.objects.select_for_update(of=("self",)).select_related("site", "company").filter(pk=data["zone_id"]).first()
    if not zone:
        raise DeviceZoneInvalid()
    _ensure_zone_is_assignable(zone=zone, company=company)
    code = data["code"].strip().upper()
    if Device.objects.filter(company=company, code=code).exists():
        raise DeviceCodeConflict()
    device = Device(
        company=company,
        zone=zone,
        hardware_id=f"web-{uuid.uuid4()}",
        code=code,
        name=data["name"].strip(),
        device_type=data.get("device_type", Device.DeviceType.DESKTOP_APP),
        configuration=data.get("configuration", {}),
    )
    try:
        device.full_clean()
        device.save()
    except IntegrityError as exc:
        raise DeviceCodeConflict() from exc
    DeviceZoneAssignment.objects.create(
        company=company,
        device=device,
        zone=zone,
        assigned_by=actor,
        assigned_at=timezone.now(),
    )
    DeviceState.objects.create(device=device, zone=zone)
    return device


@transaction.atomic
def update_device(*, device, data):
    device = Device.objects.select_for_update(of=("self",)).select_related("company", "zone", "zone__site").get(pk=device.pk)
    expected_revision = data.pop("expected_revision")
    if device.configuration_version != expected_revision:
        raise DeviceRevisionConflict()
    for field in ("name", "device_type", "configuration"):
        if field in data:
            setattr(device, field, data[field])
    if "code" in data:
        code = data["code"].strip().upper()
        if Device.objects.exclude(pk=device.pk).filter(company=device.company, code=code).exists():
            raise DeviceCodeConflict()
        device.code = code
    device.configuration_version += 1
    device.full_clean()
    try:
        device.save()
    except IntegrityError as exc:
        raise DeviceCodeConflict() from exc
    return device


@transaction.atomic
def change_device_zone(*, device, zone, actor, expected_revision, reason=""):
    device = Device.objects.select_for_update(of=("self",)).select_related("company", "zone").get(pk=device.pk)
    if device.configuration_version != expected_revision:
        raise DeviceRevisionConflict()
    zone = Zone.objects.select_for_update(of=("self",)).select_related("site", "company").get(pk=zone.pk)
    _ensure_zone_is_assignable(zone=zone, company=device.company)
    if device.zone_id == zone.id:
        return device
    now = timezone.now()
    DeviceZoneAssignment.objects.select_for_update().filter(device=device, unassigned_at__isnull=True).update(
        unassigned_at=now,
        unassigned_by=actor,
        reason=reason,
    )
    DeviceZoneAssignment.objects.create(
        company=device.company,
        device=device,
        zone=zone,
        assigned_by=actor,
        assigned_at=now,
        reason=reason,
    )
    device.zone = zone
    device.configuration_version += 1
    device.save(update_fields=["zone", "configuration_version", "updated_at"])
    DeviceState.objects.filter(device=device).update(zone=zone)
    return device


@transaction.atomic
def set_device_administrative_status(*, device, administrative_status, expected_revision):
    device = Device.objects.select_for_update().get(pk=device.pk)
    if device.configuration_version != expected_revision:
        raise DeviceRevisionConflict()
    now = timezone.now()
    device.administrative_status = administrative_status
    if administrative_status == Device.AdministrativeStatus.SUSPENDED:
        device.status = Device.Status.DISABLED
        device.deactivated_at = now
    if administrative_status == Device.AdministrativeStatus.ARCHIVED:
        device.archived_at = now
        device.status = Device.Status.DISABLED
        _invalidate_device_credentials(device=device, at=now)
        _invalidate_activation_codes(device=device, at=now)
    if administrative_status == Device.AdministrativeStatus.ACTIVE:
        if device.administrative_status == Device.AdministrativeStatus.ARCHIVED:
            _enforce_device_limit(company=device.company)
        device.archived_at = None
        device.deactivated_at = None
        device.status = Device.Status.OFFLINE if device.activation_status == Device.ActivationStatus.ACTIVATED else Device.Status.PROVISIONING
    device.configuration_version += 1
    device.save()
    return device


@transaction.atomic
def revoke_device(*, device, expected_revision):
    device = Device.objects.select_for_update().get(pk=device.pk)
    if device.configuration_version != expected_revision:
        raise DeviceRevisionConflict()
    now = timezone.now()
    _invalidate_device_credentials(device=device, at=now)
    _invalidate_activation_codes(device=device, at=now)
    device.activation_status = Device.ActivationStatus.REVOKED
    device.status = Device.Status.REVOKED
    device.connectivity_status = Device.ConnectivityStatus.OFFLINE
    device.revoked_at = now
    device.configuration_version += 1
    device.save()
    DeviceState.objects.filter(device=device).update(is_online=False, playback_status=DeviceState.PlaybackStatus.STOPPED)
    return device


@transaction.atomic
def generate_device_activation_code(*, device, created_by):
    device = Device.objects.select_for_update().get(pk=device.pk)
    if (
        device.administrative_status != Device.AdministrativeStatus.ACTIVE
        or device.activation_status == Device.ActivationStatus.REVOKED
    ):
        raise DeviceZoneInvalid(message="El dispositivo no esta activo administrativamente.")
    now = timezone.now()
    _invalidate_activation_codes(device=device, at=now)
    raw_code = "".join(secrets.choice(ACTIVATION_ALPHABET) for _ in range(12))
    activation = DeviceActivation.objects.create(
        device=device,
        code_hash=_hmac(raw_code),
        expires_at=now + settings.BM_DEVICE_ACTIVATION_CODE_TTL,
        max_attempts=settings.BM_DEVICE_ACTIVATION_MAX_ATTEMPTS,
        created_by=created_by,
    )
    return activation, _format_activation_code(raw_code)


def _get_active_activation_or_raise(*, raw_code, ip_address=None, consume=False):
    normalized = _normalize_activation_code(raw_code)
    if len(normalized) != 12:
        raise DeviceActivationInvalid()
    activation = DeviceActivation.objects.select_for_update(of=("self",)).select_related("device", "device__zone", "device__zone__site").filter(
        code_hash=_hmac(normalized)
    ).first()
    now = timezone.now()
    if not activation or not activation.is_active(at=now):
        raise DeviceActivationInvalid()
    device = activation.device
    if (
        device.administrative_status != Device.AdministrativeStatus.ACTIVE
        or device.activation_status == Device.ActivationStatus.REVOKED
        or not device.zone_id
        or device.zone.status == Zone.Status.ARCHIVED
        or device.zone.site.status == Site.Status.ARCHIVED
    ):
        raise DeviceActivationInvalid()
    activation.last_attempt_at = now
    activation.last_attempt_ip = ip_address
    activation.save(update_fields=["last_attempt_at", "last_attempt_ip", "updated_at"])
    if consume:
        activation.consumed_at = now
        activation.save(update_fields=["consumed_at", "updated_at"])
    return activation


@transaction.atomic
def validate_device_activation_code(*, raw_code, ip_address=None):
    activation = _get_active_activation_or_raise(raw_code=raw_code, ip_address=ip_address)
    return activation.device


def _new_device_credential(*, device, rotated_from=None):
    raw_secret = secrets.token_urlsafe(48)
    credential = DeviceCredential.objects.create(
        device=device,
        credential_id=str(uuid.uuid4()),
        secret_hash=_hmac(raw_secret),
        expires_at=timezone.now() + settings.BM_DEVICE_REFRESH_TOKEN_LIFETIME,
        rotated_from=rotated_from,
    )
    return credential, raw_secret


@transaction.atomic
def complete_device_activation(*, raw_code, ip_address=None, device_name="", user_agent="", app_version=""):
    activation = _get_active_activation_or_raise(raw_code=raw_code, ip_address=ip_address, consume=True)
    device = Device.objects.select_for_update().get(pk=activation.device_id)
    now = timezone.now()
    _invalidate_device_credentials(device=device, at=now)
    credential, raw_secret = _new_device_credential(device=device)
    device.activation_status = Device.ActivationStatus.ACTIVATED
    device.connectivity_status = Device.ConnectivityStatus.OFFLINE
    device.status = Device.Status.OFFLINE
    device.activated_at = device.activated_at or now
    if device_name:
        device.name = device_name.strip()
    if app_version:
        device.app_version = app_version.strip()
    metadata = dict(device.metadata or {})
    if user_agent:
        metadata["activation_user_agent"] = user_agent[:512]
    device.metadata = metadata
    device.configuration_version += 1
    device.save()
    return device, credential, raw_secret


@transaction.atomic
def rotate_device_credential(*, credential_id, raw_secret):
    credential = DeviceCredential.objects.select_for_update(of=("self",)).select_related("device", "device__company", "device__zone").filter(
        credential_id=credential_id
    ).first()
    if not credential or not hmac.compare_digest(credential.secret_hash, _hmac(raw_secret)):
        raise DeviceSessionExpired()
    now = timezone.now()
    if credential.status == DeviceCredential.Status.REVOKED:
        raise DeviceCredentialRevoked()
    if credential.status != DeviceCredential.Status.ACTIVE or (credential.expires_at and credential.expires_at <= now):
        if credential.status == DeviceCredential.Status.ACTIVE:
            credential.status = DeviceCredential.Status.EXPIRED
            credential.save(update_fields=["status"])
        raise DeviceSessionExpired()
    device = credential.device
    if device.activation_status == Device.ActivationStatus.REVOKED or device.administrative_status != Device.AdministrativeStatus.ACTIVE:
        credential.status = DeviceCredential.Status.REVOKED
        credential.revoked_at = now
        credential.save(update_fields=["status", "revoked_at"])
        raise DeviceCredentialRevoked()
    credential.status = DeviceCredential.Status.REVOKED
    credential.revoked_at = now
    credential.last_used_at = now
    credential.save(update_fields=["status", "revoked_at", "last_used_at"])
    new_credential, new_raw_secret = _new_device_credential(device=device, rotated_from=credential)
    return device, new_credential, new_raw_secret


@transaction.atomic
def revoke_device_credential_from_cookie(*, credential_id, raw_secret):
    credential = DeviceCredential.objects.select_for_update().filter(credential_id=credential_id).first()
    if not credential or not hmac.compare_digest(credential.secret_hash, _hmac(raw_secret)):
        return
    if credential.status == DeviceCredential.Status.ACTIVE:
        credential.status = DeviceCredential.Status.REVOKED
        credential.revoked_at = timezone.now()
        credential.save(update_fields=["status", "revoked_at"])


@transaction.atomic
def create_device_command(*, device, command_type, payload=None, created_by=None, expires_at=None, idempotency_key=None):
    approved_types = {
        DeviceCommand.CommandType.SET_VOLUME,
        DeviceCommand.CommandType.MUTE,
        DeviceCommand.CommandType.UNMUTE,
        DeviceCommand.CommandType.RESTART_PLAYBACK,
        DeviceCommand.CommandType.FORCE_SYNC,
        DeviceCommand.CommandType.ENABLE,
        DeviceCommand.CommandType.DISABLE,
    }
    if command_type not in approved_types:
        raise PlaybackCommandInvalid(fields={"command_type": ["Comando no valido."]})
    payload = payload or {}
    if command_type == DeviceCommand.CommandType.SET_VOLUME:
        volume = payload.get("volume")
        if not isinstance(volume, int) or isinstance(volume, bool) or not 0 <= volume <= 100:
            raise PlaybackCommandInvalid(fields={"payload": {"volume": ["Debe estar entre 0 y 100."]}})
        if set(payload) != {"volume"}:
            raise PlaybackCommandInvalid(fields={"payload": ["SET_VOLUME solo acepta el campo volume."]})
    elif payload:
        raise PlaybackCommandInvalid(fields={"payload": ["Este comando no acepta parametros."]})
    if idempotency_key:
        existing = DeviceCommand.objects.filter(company=device.company, idempotency_key=idempotency_key).first()
        if existing:
            return existing
    Device.objects.select_for_update().get(id=device.id)
    command_family = {
        DeviceCommand.CommandType.SET_VOLUME: {
            DeviceCommand.CommandType.SET_VOLUME,
            DeviceCommand.CommandType.MUTE,
            DeviceCommand.CommandType.UNMUTE,
        },
        DeviceCommand.CommandType.MUTE: {
            DeviceCommand.CommandType.SET_VOLUME,
            DeviceCommand.CommandType.MUTE,
            DeviceCommand.CommandType.UNMUTE,
        },
        DeviceCommand.CommandType.UNMUTE: {
            DeviceCommand.CommandType.SET_VOLUME,
            DeviceCommand.CommandType.MUTE,
            DeviceCommand.CommandType.UNMUTE,
        },
        DeviceCommand.CommandType.ENABLE: {
            DeviceCommand.CommandType.ENABLE,
            DeviceCommand.CommandType.DISABLE,
        },
        DeviceCommand.CommandType.DISABLE: {
            DeviceCommand.CommandType.ENABLE,
            DeviceCommand.CommandType.DISABLE,
        },
    }.get(command_type)
    if command_family:
        DeviceCommand.objects.filter(
            device=device,
            command_type__in=command_family,
            status=DeviceCommand.Status.PENDING,
        ).update(status=DeviceCommand.Status.CANCELLED)
    try:
        return DeviceCommand.objects.create(
            company=device.company,
            device=device,
            command_type=command_type,
            payload=payload,
            created_by=created_by,
            expires_at=expires_at or timezone.now() + timedelta(minutes=5),
            idempotency_key=idempotency_key,
        )
    except IntegrityError:
        return DeviceCommand.objects.get(company=device.company, idempotency_key=idempotency_key)


def _telemetry_references(*, device, event):
    from apps.catalog.models import AudioAsset
    from apps.playback.models import ContentManifest, ContentManifestItem

    manifest = None
    asset = None
    if event.get("manifest_id"):
        manifest = ContentManifest.objects.filter(
            id=event["manifest_id"], company=device.company, zone_id=device.zone_id
        ).first()
        if not manifest:
            raise PlaybackCommandInvalid(fields={"manifest_id": ["El manifiesto no pertenece al dispositivo."]})
    if event.get("asset_id"):
        if not manifest or not ContentManifestItem.objects.filter(
            manifest=manifest, audio_asset_id=event["asset_id"]
        ).exists():
            raise PlaybackCommandInvalid(fields={"asset_id": ["El asset no esta autorizado por el manifiesto."]})
        asset = AudioAsset.objects.select_related("audio_content").get(id=event["asset_id"])
    return manifest, asset


@transaction.atomic
def record_device_telemetry(*, device, events, request_id=""):
    device = Device.objects.select_for_update(of=("self",)).select_related("company", "zone").get(id=device.id)
    state, _ = DeviceState.objects.select_for_update().get_or_create(device=device, defaults={"zone": device.zone})
    now = timezone.now()
    minimum_time = now - timedelta(seconds=settings.BM_PLAYER_TELEMETRY_MAX_AGE_SECONDS)
    maximum_time = now + timedelta(seconds=settings.BM_PLAYER_TELEMETRY_FUTURE_SKEW_SECONDS)
    accepted = 0
    duplicates = 0
    for event in events:
        if not minimum_time <= event["occurred_at"] <= maximum_time:
            raise PlaybackCommandInvalid(fields={"occurred_at": ["La fecha del evento esta fuera del rango admitido."]})
        manifest, asset = _telemetry_references(device=device, event=event)
        payload = {"technical": event.get("technical", {})}
        _, created = DeviceEvent.objects.get_or_create(
            device=device,
            external_event_id=event["event_id"],
            defaults={
                "company": device.company,
                "sequence": event["sequence"],
                "event_type": event["event_type"],
                "severity": DeviceEvent.Severity.ERROR if event["event_type"] == "PLAYBACK_ERROR" else DeviceEvent.Severity.INFO,
                "occurred_at": event["occurred_at"],
                "manifest": manifest,
                "configuration_version": event.get("configuration_version"),
                "audio_asset": asset,
                "position_ms": event.get("position_ms"),
                "error_code": event.get("error_code", ""),
                "payload": payload,
                "app_version": event.get("app_version", ""),
                "request_id": request_id[:120],
            },
        )
        if not created:
            duplicates += 1
            continue
        accepted += 1
        if event["sequence"] <= state.last_sequence:
            continue
        state.last_sequence = event["sequence"]
        if event.get("position_ms") is not None:
            state.position_ms = event["position_ms"]
        if event.get("volume") is not None:
            state.volume = event["volume"]
        if event.get("playback_status"):
            state.playback_status = event["playback_status"]
        if manifest:
            state.manifest_version = manifest.version
            state.schedule_version = manifest.schedule_version
        if asset:
            state.current_audio_content = asset.audio_content
        if event["event_type"] in {"HEARTBEAT", "ONLINE", "MANIFEST_LOADED", "PLAYBACK_STARTED", "PLAYBACK_PROGRESS", "PLAYBACK_COMPLETED"}:
            state.is_online = True
            state.last_heartbeat_at = now
            device.connectivity_status = Device.ConnectivityStatus.ONLINE
            device.status = Device.Status.ONLINE
            device.last_seen_at = now
        elif event["event_type"] == "OFFLINE":
            state.is_online = False
            device.connectivity_status = Device.ConnectivityStatus.OFFLINE
            device.status = Device.Status.OFFLINE
    state.save()
    device.save(update_fields=["connectivity_status", "status", "last_seen_at", "updated_at"])
    return {"accepted": accepted, "duplicates": duplicates, "last_sequence": state.last_sequence, "received_at": now}


@transaction.atomic
def deliver_device_commands(*, device):
    now = timezone.now()
    DeviceCommand.objects.filter(
        device=device,
        status__in=[DeviceCommand.Status.PENDING, DeviceCommand.Status.DELIVERED],
        expires_at__lte=now,
    ).update(status=DeviceCommand.Status.EXPIRED)
    commands = list(
        DeviceCommand.objects.select_for_update()
        .filter(
            device=device,
            status__in=[DeviceCommand.Status.PENDING, DeviceCommand.Status.DELIVERED],
            expires_at__gt=now,
        )
        .order_by("created_at", "id")[: settings.BM_PLAYER_COMMAND_BATCH_SIZE]
    )
    pending_ids = [command.id for command in commands if command.status == DeviceCommand.Status.PENDING]
    DeviceCommand.objects.filter(id__in=pending_ids).update(status=DeviceCommand.Status.DELIVERED, delivered_at=now)
    for command in commands:
        if command.id in pending_ids:
            command.status = DeviceCommand.Status.DELIVERED
            command.delivered_at = now
    return commands


@transaction.atomic
def acknowledge_device_command(*, device, command_id, status, result=None, error_message=""):
    command = DeviceCommand.objects.select_for_update().filter(id=command_id, device=device).first()
    if not command:
        raise PlaybackCommandInvalid(message="El comando no existe.")
    now = timezone.now()
    if command.expires_at and command.expires_at <= now:
        command.status = DeviceCommand.Status.EXPIRED
        command.save(update_fields=["status"])
        raise PlaybackCommandInvalid(message="El comando ha caducado.")
    terminal = {DeviceCommand.Status.EXECUTED, DeviceCommand.Status.FAILED}
    if command.status in terminal:
        if command.status == status:
            return command
        raise PlaybackCommandInvalid(message="El comando ya tiene un resultado definitivo.")
    command.status = status
    command.acknowledged_at = command.acknowledged_at or now
    if status in terminal:
        command.executed_at = now
    command.result = result or {}
    command.error_message = error_message
    command.save(update_fields=["status", "acknowledged_at", "executed_at", "result", "error_message"])
    return command
