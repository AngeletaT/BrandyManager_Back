import hashlib
import hmac
import secrets
from datetime import timedelta

from django.contrib.auth import authenticate, get_user_model
from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.utils import get_md5_hash_password

from apps.users.emails import send_email_verification_email, send_password_reset_email
from apps.users.exceptions import EmailAlreadyRegistered, EmailNotVerified, InvalidCredentials, PasswordResetTokenInvalid, SessionExpired, UserInactive, VerificationTokenInvalid
from apps.users.models import UserActionToken
from apps.users.selectors import build_user_session_payload, get_active_company_membership, get_latest_action_token, get_user_by_email, user_exists_by_email


UserModel = get_user_model()

EMAIL_VERIFICATION_TOKEN_TTL = timedelta(hours=24)
PASSWORD_RESET_TOKEN_TTL = timedelta(hours=1)
EMAIL_VERIFICATION_RESEND_COOLDOWN = timedelta(minutes=2)
PASSWORD_RESET_REQUEST_COOLDOWN = timedelta(minutes=2)
MEMBERSHIP_LAST_ACCESS_UPDATE_INTERVAL = timedelta(minutes=15)


def build_user_tokens(*, user):
    refresh = RefreshToken.for_user(user)

    return {
        "refresh": str(refresh),
        "access": str(refresh.access_token),
    }


def build_refresh_and_access_tokens(*, user):
    refresh = RefreshToken.for_user(user)
    return str(refresh), str(refresh.access_token)


def ensure_user_can_start_session(*, user):
    if not user.is_active:
        raise UserInactive()
    if not user.email_verified_at:
        raise EmailNotVerified()


def touch_active_membership_last_access(*, user, at=None):
    at = at or timezone.now()
    membership = get_active_company_membership(user=user)
    if not membership:
        return
    if membership.last_access_at and membership.last_access_at > at - MEMBERSHIP_LAST_ACCESS_UPDATE_INTERVAL:
        return
    membership.last_access_at = at
    membership.save(update_fields=["last_access_at", "updated_at"])


@transaction.atomic
def register_client_user(*, data):
    email = data["email"]

    if user_exists_by_email(email=email):
        raise EmailAlreadyRegistered()

    user = UserModel.objects.create_user(
        email=email,
        password=data["password"],
        first_name=data.get("first_name", ""),
        last_name=data.get("last_name", ""),
    )
    _, raw_token = create_email_verification_token(user=user)
    transaction.on_commit(lambda: send_email_verification_email(user=user, raw_token=raw_token))

    return user


def login_user(*, data):
    user = authenticate(email=data["email"], password=data["password"])

    if user is None:
        inactive_user = UserModel.objects.filter(email=data["email"], is_active=False).first()
        if inactive_user and inactive_user.check_password(data["password"]):
            raise UserInactive()
        raise InvalidCredentials()

    ensure_user_can_start_session(user=user)
    refresh, access = build_refresh_and_access_tokens(user=user)
    touch_active_membership_last_access(user=user)

    return build_user_session_payload(user=user, access=access), refresh


def get_user_from_refresh_token(*, refresh_token):
    try:
        token = RefreshToken(refresh_token)
        user_id = token[api_settings.USER_ID_CLAIM]
        user = UserModel.objects.get(**{api_settings.USER_ID_FIELD: user_id})
    except (TokenError, KeyError, UserModel.DoesNotExist) as exc:
        raise SessionExpired() from exc
    token_password_hash = token.get(api_settings.REVOKE_TOKEN_CLAIM)
    if token_password_hash != get_md5_hash_password(user.password):
        raise SessionExpired()
    return user, token


@transaction.atomic
def refresh_user_session(*, refresh_token):
    user, token = get_user_from_refresh_token(refresh_token=refresh_token)
    ensure_user_can_start_session(user=user)

    try:
        token.blacklist()
    except AttributeError as exc:
        raise SessionExpired() from exc

    new_refresh, access = build_refresh_and_access_tokens(user=user)
    touch_active_membership_last_access(user=user)
    return build_user_session_payload(user=user, access=access), new_refresh


@transaction.atomic
def logout_user_session(*, refresh_token):
    if not refresh_token:
        return
    try:
        token = RefreshToken(refresh_token)
        token.blacklist()
    except TokenError:
        return


def validate_user_action_token(*, raw_token, purpose, at=None):
    now = at or timezone.now()
    token_hash = hash_action_token(raw_token=raw_token)
    action_token = (
        UserActionToken.objects.select_related("user")
        .filter(token_hash=token_hash, purpose=purpose)
        .first()
    )
    if not action_token or not action_token.is_valid(at=now):
        return None
    return action_token


def generate_raw_action_token():
    return secrets.token_urlsafe(32)


def hash_action_token(*, raw_token):
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        raw_token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


@transaction.atomic
def create_user_action_token(*, user, purpose, ttl, metadata=None):
    now = timezone.now()
    UserActionToken.objects.select_for_update().filter(
        user=user,
        purpose=purpose,
        consumed_at__isnull=True,
        revoked_at__isnull=True,
    ).update(revoked_at=now)

    raw_token = generate_raw_action_token()
    action_token = UserActionToken.objects.create(
        user=user,
        purpose=purpose,
        token_hash=hash_action_token(raw_token=raw_token),
        expires_at=now + ttl,
        metadata=metadata or {},
    )
    return action_token, raw_token


def create_email_verification_token(*, user):
    return create_user_action_token(
        user=user,
        purpose=UserActionToken.Purpose.VERIFY_EMAIL,
        ttl=EMAIL_VERIFICATION_TOKEN_TTL,
    )


def create_password_reset_token_for_email(*, email):
    user = get_user_by_email(email=email)
    if not user or not user.is_active:
        return None, None

    return create_password_reset_token_for_user(user=user)


def create_password_reset_token_for_user(*, user):
    return create_user_action_token(
        user=user,
        purpose=UserActionToken.Purpose.RESET_PASSWORD,
        ttl=PASSWORD_RESET_TOKEN_TTL,
    )


@transaction.atomic
def consume_user_action_token(*, raw_token, purpose, at=None):
    now = at or timezone.now()
    token_hash = hash_action_token(raw_token=raw_token)

    try:
        action_token = UserActionToken.objects.select_for_update().select_related("user").get(
            token_hash=token_hash,
            purpose=purpose,
        )
    except UserActionToken.DoesNotExist as exc:
        raise DjangoValidationError("Token no valido.") from exc

    if not action_token.is_valid(at=now):
        raise DjangoValidationError("Token no valido.")

    action_token.consumed_at = now
    action_token.save(update_fields=["consumed_at"])

    if purpose == UserActionToken.Purpose.VERIFY_EMAIL and not action_token.user.email_verified_at:
        action_token.user.email_verified_at = now
        action_token.user.save(update_fields=["email_verified_at", "updated_at"])

    return action_token


def token_can_be_resent(*, user, purpose, at=None):
    at = at or timezone.now()
    latest_token = get_latest_action_token(user=user, purpose=purpose)
    if latest_token is None:
        return True
    return latest_token.created_at <= at - EMAIL_VERIFICATION_RESEND_COOLDOWN


def password_reset_can_be_requested(*, user, at=None):
    at = at or timezone.now()
    latest_token = get_latest_action_token(user=user, purpose=UserActionToken.Purpose.RESET_PASSWORD)
    if latest_token is None:
        return True
    return latest_token.created_at <= at - PASSWORD_RESET_REQUEST_COOLDOWN


@transaction.atomic
def resend_email_verification(*, email):
    user = get_user_by_email(email=email)
    if not user or user.email_verified_at:
        return
    if not token_can_be_resent(user=user, purpose=UserActionToken.Purpose.VERIFY_EMAIL):
        return

    _, raw_token = create_email_verification_token(user=user)
    transaction.on_commit(lambda: send_email_verification_email(user=user, raw_token=raw_token))


@transaction.atomic
def request_password_reset(*, email):
    user = get_user_by_email(email=email)
    if not user or not user.is_active:
        hash_action_token(raw_token=generate_raw_action_token())
        return
    if not password_reset_can_be_requested(user=user):
        return

    _, raw_token = create_password_reset_token_for_user(user=user)
    transaction.on_commit(lambda: send_password_reset_email(user=user, raw_token=raw_token))


def password_reset_token_is_valid(*, raw_token):
    return bool(
        validate_user_action_token(
            raw_token=raw_token,
            purpose=UserActionToken.Purpose.RESET_PASSWORD,
        )
    )


@transaction.atomic
def confirm_password_reset(*, raw_token, password):
    action_token = validate_user_action_token(
        raw_token=raw_token,
        purpose=UserActionToken.Purpose.RESET_PASSWORD,
    )
    if not action_token:
        raise PasswordResetTokenInvalid()

    user = UserModel.objects.select_for_update().get(pk=action_token.user_id)
    validate_password(password, user=user)

    action_token = consume_user_action_token(
        raw_token=raw_token,
        purpose=UserActionToken.Purpose.RESET_PASSWORD,
    )
    UserActionToken.objects.select_for_update().filter(
        user=user,
        purpose=UserActionToken.Purpose.RESET_PASSWORD,
        consumed_at__isnull=True,
        revoked_at__isnull=True,
    ).exclude(pk=action_token.pk).update(revoked_at=timezone.now())

    user.set_password(password)
    user.save(update_fields=["password", "updated_at"])
    return user


def confirm_email_verification(*, raw_token):
    try:
        action_token = consume_user_action_token(
            raw_token=raw_token,
            purpose=UserActionToken.Purpose.VERIFY_EMAIL,
        )
    except DjangoValidationError as exc:
        raise VerificationTokenInvalid() from exc

    return action_token.user
