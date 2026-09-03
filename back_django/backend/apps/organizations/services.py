from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.contrib.auth.password_validation import validate_password
from django.db import IntegrityError, transaction
from django.utils.text import slugify
from django.utils import timezone

from apps.authorization.catalog import OFFICIAL_COMPANY_ROLE_CODES, OWNER_COMPANY_ROLE_CODE
from apps.authorization.models import CompanyRole
from apps.authorization.services import get_company_scope, get_or_create_site_scope, get_or_create_zone_scope
from apps.audit.services import register_audit_log
from apps.billing.selectors import get_current_subscription_for_company
from apps.organizations.emails import send_company_invitation_email
from apps.organizations.exceptions import CompanyTaxIdConflict, InvitationConflict, InvitationTokenInvalid, InvalidRoleAssignment, PlanLimitReached, ProtectedOwner, SiteArchived, SiteCodeConflict, SiteNotFound, ZoneCodeConflict
from apps.organizations.models import Company, CompanyInvitation, CompanyMembership, MembershipGrant, MembershipPermissionOverride, ResourceScope, Site, Zone
from apps.organizations.normalization import normalize_tax_id
from apps.support.services import INCIDENT_TYPE_MEMBERSHIP_TRANSFER_REQUEST
from apps.users.services import generate_raw_action_token, hash_action_token


User = get_user_model()
COMPANY_INVITATION_TOKEN_TTL = timedelta(days=7)
COMPANY_INVITATION_RESEND_COOLDOWN = timedelta(minutes=2)


def user_can_perform_internal_support_action(*, user):
    return user.platform_roles.filter(revoked_at__isnull=True, role__is_active=True).exists()


def _generate_code(*, model, company, name, parent_filter=None):
    base = slugify(name).upper()[:48] or "RESOURCE"
    code = base
    suffix = 1
    queryset = model.objects.filter(company=company)
    if parent_filter:
        queryset = queryset.filter(**parent_filter)
    while queryset.filter(code=code).exists():
        suffix += 1
        code = f"{base[:44]}-{suffix}"
    return code


def _get_limit(*, company, key):
    subscription = get_current_subscription_for_company(company=company)
    if not subscription:
        return None
    return subscription.effective_limits().get(key)


def _check_plan_limit(*, company, key, current_count):
    limit = _get_limit(company=company, key=key)
    if limit is not None and current_count >= limit:
        raise PlanLimitReached(limit_key=key)


def _ensure_site_code_available(*, company, code, site=None):
    queryset = Site.objects.filter(company=company, code=code)
    if site:
        queryset = queryset.exclude(pk=site.pk)
    if queryset.exists():
        raise SiteCodeConflict()


def _ensure_zone_code_available(*, site, code, zone=None):
    queryset = Zone.objects.filter(site=site, code=code)
    if zone:
        queryset = queryset.exclude(pk=zone.pk)
    if queryset.exists():
        raise ZoneCodeConflict()


def _get_role(*, code):
    if code not in OFFICIAL_COMPANY_ROLE_CODES:
        raise InvalidRoleAssignment()
    try:
        return CompanyRole.objects.get(company=None, code=code, is_active=True)
    except CompanyRole.DoesNotExist as exc:
        raise InvalidRoleAssignment() from exc


def _is_owner_membership(*, membership):
    return MembershipGrant.objects.filter(
        membership=membership,
        role__code=OWNER_COMPANY_ROLE_CODE,
        is_active=True,
        ends_at__isnull=True,
    ).exists()


def _resolve_scope_targets(*, company, role_code, site_ids=None, zone_ids=None):
    site_ids = site_ids or []
    zone_ids = zone_ids or []
    if role_code in {"OWNER", "MANAGER", "EDITOR_PLAYLISTS"}:
        return [get_company_scope(company=company)]
    if role_code == "OPERADOR_SEDES" and not site_ids and not zone_ids:
        raise InvalidRoleAssignment()
    if role_code == "VIEWER" and not site_ids and not zone_ids:
        return [get_company_scope(company=company)]

    scopes = []
    sites = list(Site.objects.filter(company=company, id__in=site_ids, status__in=[Site.Status.ACTIVE, Site.Status.INACTIVE]))
    zones = list(Zone.objects.filter(company=company, id__in=zone_ids, status__in=[Zone.Status.ACTIVE, Zone.Status.INACTIVE, Zone.Status.SUSPENDED]).select_related("site"))
    if len(sites) != len(set(str(site_id) for site_id in site_ids)):
        raise InvalidRoleAssignment()
    if len(zones) != len(set(str(zone_id) for zone_id in zone_ids)):
        raise InvalidRoleAssignment()
    if any(zone.site.status == Site.Status.ARCHIVED for zone in zones):
        raise InvalidRoleAssignment()
    for site in sites:
        scopes.append(get_or_create_site_scope(site=site))
    for zone in zones:
        scopes.append(get_or_create_zone_scope(zone=zone))
    if not scopes:
        scopes.append(get_company_scope(company=company))
    return scopes


def _invitation_scope_targets(*, invitation):
    return _resolve_scope_targets(
        company=invitation.company,
        role_code=invitation.role.code,
        site_ids=invitation.site_ids,
        zone_ids=invitation.zone_ids,
    )


def _active_invitation_count(*, company):
    now = timezone.now()
    return CompanyInvitation.objects.filter(
        company=company,
        accepted_at__isnull=True,
        cancelled_at__isnull=True,
        expires_at__gt=now,
    ).count()


def _check_user_seat_limit(*, company):
    active_or_suspended_memberships = CompanyMembership.objects.filter(company=company).exclude(status=CompanyMembership.Status.REVOKED).count()
    _check_plan_limit(
        company=company,
        key="users",
        current_count=active_or_suspended_memberships + _active_invitation_count(company=company),
    )


def _generate_invitation_token():
    raw_token = generate_raw_action_token()
    return raw_token, hash_action_token(raw_token=raw_token)


def _validate_invitation_for_token(*, raw_token, for_update=False, at=None):
    now = at or timezone.now()
    token_hash = hash_action_token(raw_token=raw_token)
    queryset = CompanyInvitation.objects.select_related("company", "role", "invited_by")
    if for_update:
        queryset = queryset.select_for_update(of=("self",))
    invitation = queryset.filter(token_hash=token_hash).first()
    if not invitation or not invitation.is_pending(at=now):
        raise InvitationTokenInvalid()
    return invitation


@transaction.atomic
def update_company_profile(*, company, data, actor):
    before_data = {
        "legal_name": company.legal_name,
        "trade_name": company.trade_name,
        "tax_id": company.tax_id,
        "billing_email": company.billing_email,
        "contact_email": company.contact_email,
        "phone": company.phone,
        "country_code": company.country_code,
        "default_timezone": company.default_timezone,
        "default_language": company.default_language,
        "settings": company.settings,
    }
    if "tax_id" in data:
        normalized_tax_id = normalize_tax_id(data["tax_id"])
        if Company.objects.filter(tax_id=normalized_tax_id).exclude(pk=company.pk).exists():
            raise CompanyTaxIdConflict()
        data["tax_id"] = normalized_tax_id
    for field in [
        "legal_name",
        "trade_name",
        "tax_id",
        "billing_email",
        "contact_email",
        "phone",
        "country_code",
        "default_timezone",
        "default_language",
    ]:
        if field in data:
            setattr(company, field, data[field])
    if "sector" in data:
        settings = dict(company.settings or {})
        onboarding_settings = dict(settings.get("onboarding", {}))
        onboarding_settings["sector"] = data["sector"]
        settings["onboarding"] = onboarding_settings
        company.settings = settings
    company.full_clean()
    try:
        company.save()
    except IntegrityError as exc:
        if "uniq_company_tax_id" in str(exc):
            raise CompanyTaxIdConflict() from exc
        raise
    register_audit_log(
        action="company.update",
        entity_type="Company",
        company=company,
        actor_user=actor,
        entity_id=company.id,
        entity_label=company.trade_name,
        before_data=before_data,
        after_data=data,
    )
    return company


@transaction.atomic
def create_site(*, company, data, actor):
    company = Company.objects.select_for_update().get(pk=company.pk)
    _check_plan_limit(
        company=company,
        key="sites",
        current_count=Site.objects.filter(company=company).exclude(status=Site.Status.ARCHIVED).count(),
    )
    code = data.get("code") or _generate_code(model=Site, company=company, name=data["name"])
    _ensure_site_code_available(company=company, code=code)
    site = Site(
        company=company,
        name=data["name"],
        code=code,
        site_type=data.get("site_type", Site.SiteType.BRANCH),
        description=data.get("description", ""),
        address_line_1=data["address_line_1"],
        address_line_2=data.get("address_line_2", ""),
        postal_code=data.get("postal_code", ""),
        city=data["city"],
        province=data.get("province", ""),
        country_code=data.get("country_code") or company.country_code,
        timezone=data.get("timezone") or company.default_timezone,
        contact_name=data.get("contact_name", ""),
        contact_email=data.get("contact_email", ""),
        contact_phone=data.get("contact_phone", ""),
        metadata={},
    )
    site.full_clean()
    try:
        site.save()
    except IntegrityError as exc:
        if "uniq_site_company_code" in str(exc):
            raise SiteCodeConflict() from exc
        raise
    get_or_create_site_scope(site=site)
    return site


@transaction.atomic
def update_site(*, site, data):
    for field in [
        "name",
        "code",
        "site_type",
        "description",
        "address_line_1",
        "address_line_2",
        "postal_code",
        "city",
        "province",
        "country_code",
        "timezone",
        "contact_name",
        "contact_email",
        "contact_phone",
    ]:
        if field in data:
            setattr(site, field, data[field])
    if "code" in data:
        _ensure_site_code_available(company=site.company, code=site.code, site=site)
    site.full_clean()
    try:
        site.save()
    except IntegrityError as exc:
        if "uniq_site_company_code" in str(exc):
            raise SiteCodeConflict() from exc
        raise
    return site


@transaction.atomic
def archive_site(*, site):
    site.status = Site.Status.ARCHIVED
    site.archived_at = timezone.now()
    site.save(update_fields=["status", "archived_at", "updated_at"])
    Zone.objects.filter(site=site).exclude(status=Zone.Status.ARCHIVED).update(
        status=Zone.Status.ARCHIVED,
        archived_at=site.archived_at,
        updated_at=site.archived_at,
    )
    return site


@transaction.atomic
def reactivate_site(*, site):
    company = Company.objects.select_for_update().get(pk=site.company_id)
    _check_plan_limit(
        company=company,
        key="sites",
        current_count=Site.objects.filter(company=company).exclude(status=Site.Status.ARCHIVED).exclude(pk=site.pk).count(),
    )
    site.status = Site.Status.ACTIVE
    site.archived_at = None
    site.save(update_fields=["status", "archived_at", "updated_at"])
    return site


activate_site = reactivate_site


@transaction.atomic
def create_zone(*, company, data):
    company = Company.objects.select_for_update().get(pk=company.pk)
    _check_plan_limit(
        company=company,
        key="zones",
        current_count=Zone.objects.filter(company=company).exclude(status=Zone.Status.ARCHIVED).count(),
    )
    try:
        site = Site.objects.get(company=company, id=data["site_id"])
    except Site.DoesNotExist as exc:
        raise SiteNotFound() from exc
    if site.status == Site.Status.ARCHIVED:
        raise SiteArchived()
    code = data.get("code") or _generate_code(model=Zone, company=company, name=data["name"], parent_filter={"site": site})
    _ensure_zone_code_available(site=site, code=code)
    zone = Zone(
        company=company,
        site=site,
        name=data["name"],
        code=code,
        description=data.get("description", ""),
        timezone=data.get("timezone") or None,
        metadata={},
    )
    zone.full_clean()
    try:
        zone.save()
    except IntegrityError as exc:
        if "uniq_zone_site_code" in str(exc):
            raise ZoneCodeConflict() from exc
        raise
    get_or_create_zone_scope(zone=zone)
    return zone


@transaction.atomic
def update_zone(*, zone, data):
    for field in ["name", "code", "description", "timezone"]:
        if field in data:
            setattr(zone, field, data[field])
    if "code" in data:
        _ensure_zone_code_available(site=zone.site, code=zone.code, zone=zone)
    zone.full_clean()
    try:
        zone.save()
    except IntegrityError as exc:
        if "uniq_zone_site_code" in str(exc):
            raise ZoneCodeConflict() from exc
        raise
    return zone


@transaction.atomic
def archive_zone(*, zone):
    zone.status = Zone.Status.ARCHIVED
    zone.archived_at = timezone.now()
    zone.save(update_fields=["status", "archived_at", "updated_at"])
    return zone


@transaction.atomic
def reactivate_zone(*, zone):
    if zone.site.status == Site.Status.ARCHIVED:
        raise SiteArchived()
    company = Company.objects.select_for_update().get(pk=zone.company_id)
    _check_plan_limit(
        company=company,
        key="zones",
        current_count=Zone.objects.filter(company=company).exclude(status=Zone.Status.ARCHIVED).exclude(pk=zone.pk).count(),
    )
    zone.status = Zone.Status.ACTIVE
    zone.archived_at = None
    zone.save(update_fields=["status", "archived_at", "updated_at"])
    return zone


activate_zone = reactivate_zone


@transaction.atomic
def invite_company_member(*, company, email, first_name, last_name, role_code, invited_by, site_ids=None, zone_ids=None):
    if role_code == OWNER_COMPANY_ROLE_CODE:
        raise InvalidRoleAssignment()
    company = Company.objects.select_for_update().get(pk=company.pk)
    _check_user_seat_limit(company=company)
    normalized_email = User.objects.normalize_email(email)
    user = User.objects.filter(email__iexact=normalized_email).first()
    if user and (user.is_staff or user.is_superuser or user.platform_roles.filter(revoked_at__isnull=True).exists()):
        raise InvalidRoleAssignment()
    if user and user.company_memberships.exists():
        raise InvitationConflict(
            code="user_already_belongs_to_company",
            message="El usuario ya pertenece a una empresa. Debe gestionarse mediante soporte.",
            fields={"email": ["El usuario ya pertenece a una empresa."]},
        )
    now = timezone.now()
    CompanyInvitation.objects.select_for_update().filter(
        company=company,
        invited_email__iexact=normalized_email,
        accepted_at__isnull=True,
        cancelled_at__isnull=True,
        expires_at__lte=now,
    ).update(cancelled_at=now)
    if CompanyInvitation.objects.filter(
        company=company,
        invited_email__iexact=normalized_email,
        accepted_at__isnull=True,
        cancelled_at__isnull=True,
        expires_at__gt=now,
    ).exists():
        raise InvitationConflict(
            code="invitation_already_pending",
            message="Ya existe una invitacion pendiente para este email.",
            fields={"email": ["Ya existe una invitacion pendiente para este email."]},
        )
    role = _get_role(code=role_code)
    scopes = _resolve_scope_targets(company=company, role_code=role_code, site_ids=site_ids, zone_ids=zone_ids)
    raw_token, token_hash = _generate_invitation_token()
    invitation = CompanyInvitation.objects.create(
        company=company,
        invited_email=normalized_email,
        first_name=first_name,
        last_name=last_name,
        role=role,
        invited_by=invited_by,
        token_hash=token_hash,
        expires_at=now + COMPANY_INVITATION_TOKEN_TTL,
        last_sent_at=now,
        site_ids=[str(site_id) for site_id in (site_ids or [])],
        zone_ids=[str(zone_id) for zone_id in (zone_ids or [])],
    )
    transaction.on_commit(lambda: send_company_invitation_email(invitation=invitation, raw_token=raw_token))
    invitation._resolved_scopes = scopes
    invitation._raw_token_for_tests = raw_token
    return invitation


def validate_company_invitation_token(*, raw_token):
    try:
        return _validate_invitation_for_token(raw_token=raw_token)
    except InvitationTokenInvalid:
        return None


def get_invitation_scopes(*, invitation, strict=False):
    try:
        return _invitation_scope_targets(invitation=invitation)
    except InvalidRoleAssignment:
        if strict:
            raise
        return []


@transaction.atomic
def accept_company_invitation(*, raw_token, password=None):
    invitation = _validate_invitation_for_token(raw_token=raw_token, for_update=True)
    company = Company.objects.select_for_update().get(pk=invitation.company_id)
    user = User.objects.select_for_update().filter(email__iexact=invitation.invited_email).first()
    now = timezone.now()

    if user and (user.is_staff or user.is_superuser or user.platform_roles.filter(revoked_at__isnull=True).exists()):
        raise InvalidRoleAssignment()
    if user and user.company_memberships.exists():
        raise InvitationConflict(
            code="user_already_belongs_to_company",
            message="El usuario ya pertenece a una empresa. Debe gestionarse mediante soporte.",
            fields={"email": ["El usuario ya pertenece a una empresa."]},
        )
    if not user:
        if not password:
            raise ValidationError("La contrasena es obligatoria para aceptar esta invitacion.")
        user = User(
            email=invitation.invited_email,
            first_name=invitation.first_name,
            last_name=invitation.last_name,
            email_verified_at=now,
            is_active=True,
        )
        validate_password(password, user=user)
        user.set_password(password)
        user.save()
    else:
        if password:
            validate_password(password, user=user)
            user.set_password(password)
        if invitation.first_name and not user.first_name:
            user.first_name = invitation.first_name
        if invitation.last_name and not user.last_name:
            user.last_name = invitation.last_name
        if not user.email_verified_at:
            user.email_verified_at = now
        user.is_active = True
        user.save(update_fields=["first_name", "last_name", "password", "email_verified_at", "is_active", "updated_at"])

    membership = CompanyMembership.objects.create(
        company=company,
        user=user,
        status=CompanyMembership.Status.ACTIVE,
        invited_by=invitation.invited_by,
        invited_at=invitation.created_at,
        accepted_at=now,
    )
    scopes = _invitation_scope_targets(invitation=invitation)
    for scope in scopes:
        MembershipGrant.objects.create(membership=membership, role=invitation.role, scope=scope, assigned_by=invitation.invited_by)
    invitation.accepted_by = user
    invitation.accepted_at = now
    invitation.save(update_fields=["accepted_by", "accepted_at", "updated_at"])
    return membership


@transaction.atomic
def update_member_role_and_scopes(*, membership, role_code, actor, site_ids=None, zone_ids=None):
    if _is_owner_membership(membership=membership) or role_code == OWNER_COMPANY_ROLE_CODE:
        raise ProtectedOwner()
    role = _get_role(code=role_code)
    now = timezone.now()
    MembershipGrant.objects.filter(membership=membership, is_active=True).update(is_active=False, ends_at=now)
    for scope in _resolve_scope_targets(company=membership.company, role_code=role_code, site_ids=site_ids, zone_ids=zone_ids):
        MembershipGrant.objects.create(membership=membership, role=role, scope=scope, assigned_by=actor)
    return membership


@transaction.atomic
def suspend_member(*, membership):
    if _is_owner_membership(membership=membership):
        raise ProtectedOwner()
    membership.status = CompanyMembership.Status.SUSPENDED
    membership.save(update_fields=["status", "updated_at"])
    return membership


@transaction.atomic
def reactivate_member(*, membership):
    if _is_owner_membership(membership=membership):
        raise ProtectedOwner()
    membership.status = CompanyMembership.Status.ACTIVE
    membership.save(update_fields=["status", "updated_at"])
    return membership


@transaction.atomic
def cancel_invitation(*, invitation):
    invitation = CompanyInvitation.objects.select_for_update().get(pk=invitation.pk)
    if not invitation.is_pending():
        raise InvitationConflict()
    invitation.cancelled_at = timezone.now()
    invitation.save(update_fields=["cancelled_at", "updated_at"])
    return invitation


@transaction.atomic
def resend_invitation(*, invitation):
    invitation = (
        CompanyInvitation.objects.select_for_update(of=("self",))
        .select_related("company", "role", "invited_by")
        .get(pk=invitation.pk)
    )
    now = timezone.now()
    if not invitation.is_pending(at=now):
        raise InvitationConflict()
    if invitation.last_sent_at and invitation.last_sent_at > now - COMPANY_INVITATION_RESEND_COOLDOWN:
        return invitation
    raw_token, token_hash = _generate_invitation_token()
    invitation.token_hash = token_hash
    invitation.expires_at = now + COMPANY_INVITATION_TOKEN_TTL
    invitation.last_sent_at = now
    invitation.save(update_fields=["token_hash", "expires_at", "last_sent_at", "updated_at"])
    transaction.on_commit(lambda: send_company_invitation_email(invitation=invitation, raw_token=raw_token))
    invitation._raw_token_for_tests = raw_token
    return invitation


@transaction.atomic
def transfer_membership_by_support_ticket(
    *,
    membership,
    target_company,
    support_incident,
    performed_by,
    reason,
):
    if not user_can_perform_internal_support_action(user=performed_by):
        raise ValidationError("Solo un administrador interno puede ejecutar esta operacion.")
    if support_incident.incident_type != INCIDENT_TYPE_MEMBERSHIP_TRANSFER_REQUEST:
        raise ValidationError("La incidencia no corresponde a una transferencia de membresia.")
    if support_incident.status not in {
        support_incident.Status.OPEN,
        support_incident.Status.ACKNOWLEDGED,
        support_incident.Status.INVESTIGATING,
    }:
        raise ValidationError("La incidencia no esta en un estado operable.")

    membership = CompanyMembership.objects.select_for_update().select_related("company", "user").get(pk=membership.pk)
    source_company = membership.company
    expected_metadata = support_incident.metadata or {}
    if expected_metadata.get("membership_id") != str(membership.id):
        raise ValidationError("La incidencia no corresponde a esta membresia.")
    if expected_metadata.get("source_company_id") != str(source_company.id):
        raise ValidationError("La empresa origen no coincide con la incidencia.")
    if expected_metadata.get("target_company_id") != str(target_company.id):
        raise ValidationError("La empresa destino no coincide con la incidencia.")
    if target_company.id == source_company.id:
        raise ValidationError("La empresa destino debe ser distinta.")

    now = timezone.now()
    before_data = {
        "membership_id": str(membership.id),
        "user_id": str(membership.user_id),
        "company_id": str(source_company.id),
        "status": membership.status,
    }

    MembershipGrant.objects.select_for_update().filter(
        membership=membership,
        is_active=True,
    ).update(is_active=False, ends_at=now, updated_at=now)
    MembershipPermissionOverride.objects.select_for_update().filter(
        membership=membership,
        ends_at__isnull=True,
    ).update(ends_at=now, updated_at=now)

    membership.company = target_company
    membership.status = CompanyMembership.Status.INVITED
    membership.invited_by = None
    membership.invited_at = now
    membership.accepted_at = None
    membership.last_access_at = None
    membership.save(
        update_fields=[
            "company",
            "status",
            "invited_by",
            "invited_at",
            "accepted_at",
            "last_access_at",
            "updated_at",
        ]
    )

    support_incident.status = support_incident.Status.RESOLVED
    support_incident.resolved_at = now
    support_incident.assigned_to = performed_by
    support_incident.save(update_fields=["status", "resolved_at", "assigned_to", "updated_at"])

    after_data = {
        "membership_id": str(membership.id),
        "user_id": str(membership.user_id),
        "company_id": str(target_company.id),
        "status": membership.status,
        "support_incident_id": str(support_incident.id),
        "reason": reason,
    }
    register_audit_log(
        action="company_membership.transfer_by_support_ticket",
        entity_type="CompanyMembership",
        company=target_company,
        actor_user=performed_by,
        entity_id=membership.id,
        entity_label=membership.user.email,
        before_data=before_data,
        after_data=after_data,
    )
    return membership
