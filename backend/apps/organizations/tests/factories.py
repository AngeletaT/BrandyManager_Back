from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.authorization.models import CompanyRole, Permission
from apps.billing.models import License, Plan, Subscription
from apps.catalog.models import AudioAsset, AudioContent, AudioMessage, Genre, Song, SongTag, Tag, TagCategory
from apps.devices.models import Device
from apps.organizations.models import Company, CompanyMembership, ResourceScope, Site, Zone
from apps.playback.models import ContentManifest, PlaybackPolicy
from apps.playlists.models import Channel, Playlist, PlaylistItem
from apps.scheduling.models import Schedule


User = get_user_model()


def user(email="user@example.com"):
    return User.objects.create_user(email=email, password="StrongPass123!")


def company(code="acme"):
    return Company.objects.create(
        legal_name=f"{code} Legal",
        trade_name=code,
        tax_id=f"TAX-{code}",
        billing_email=f"billing-{code}@example.com",
        contact_email=f"contact-{code}@example.com",
        country_code="ES",
        default_timezone="Europe/Madrid",
        default_language="es",
    )


def membership(company_obj, user_obj):
    return CompanyMembership.objects.create(company=company_obj, user=user_obj, status=CompanyMembership.Status.ACTIVE)


def site(company_obj, code="site"):
    return Site.objects.create(
        company=company_obj,
        name=code,
        code=code,
        address_line_1="Street",
        postal_code="28001",
        city="Madrid",
        country_code="ES",
        timezone="Europe/Madrid",
    )


def zone(company_obj, site_obj, code="zone"):
    return Zone.objects.create(company=company_obj, site=site_obj, name=code, code=code)


def scope(company_obj, scope_type="COMPANY", **kwargs):
    return ResourceScope.objects.create(company=company_obj, scope_type=scope_type, name=f"{scope_type} scope", **kwargs)


def permission(code="zones.manage"):
    return Permission.objects.create(code=code, name=code, module=code.split(".")[0], permission_level=Permission.PermissionLevel.COMPANY)


def company_role(code="MANAGER", company_obj=None):
    return CompanyRole.objects.create(company=company_obj, code=code, name=code)


def plan():
    plan_obj, _ = Plan.objects.get_or_create(
        code="basic",
        defaults={
            "name": "Basic",
            "billing_interval": Plan.BillingInterval.MONTHLY,
            "base_price": "10.00",
            "currency": "EUR",
        },
    )
    return plan_obj


def subscription(company_obj):
    now = timezone.now()
    return Subscription.objects.create(
        company=company_obj,
        plan=plan(),
        status=Subscription.Status.ACTIVE,
        started_at=now,
        current_period_start=now,
        current_period_end=now + timedelta(days=30),
        license_quantity=10,
        unit_price="10.00",
        currency="EUR",
    )


def license(company_obj, code="lic"):
    return License.objects.create(company=company_obj, subscription=subscription(company_obj), code=code)


def genre():
    genre_obj, _ = Genre.objects.get_or_create(slug="pop", defaults={"name": "Pop"})
    return genre_obj


def tag(slug="relaxed", name="Relaxed"):
    category, _ = TagCategory.objects.get_or_create(code="MOOD", defaults={"name": "Mood"})
    tag_obj, _ = Tag.objects.get_or_create(category=category, slug=slug, defaults={"name": name})
    return tag_obj


def song(title="Song"):
    audio = AudioContent.objects.create(content_type=AudioContent.ContentType.SONG, title=title, internal_code=title.lower())
    return Song.objects.create(audio_content=audio, genre=genre())


def audio_message(title="Message"):
    audio = AudioContent.objects.create(content_type=AudioContent.ContentType.MESSAGE, title=title, internal_code=title.lower())
    return AudioMessage.objects.create(audio_content=audio, message_type=AudioMessage.MessageType.CORPORATE)


def asset(audio_content, role=AudioAsset.AssetRole.ORIGINAL, version=1, primary=False, key="key"):
    return AudioAsset.objects.create(
        audio_content=audio_content,
        asset_role=role,
        storage_backend="s3",
        storage_key=key,
        original_filename="audio.mp3",
        mime_type="audio/mpeg",
        container_format="mp3",
        codec="mp3",
        size_bytes=100,
        checksum_sha256="a" * 64,
        version=version,
        processing_status=AudioAsset.ProcessingStatus.READY,
        is_primary=primary,
    )


def playlist_with_song(song_obj):
    playlist = Playlist.objects.create(name="Playlist", code="playlist")
    PlaylistItem.objects.create(playlist=playlist, song=song_obj, position=1, weight=1)
    return playlist


def channel(company_obj=None):
    return Channel.objects.create(owner_company=company_obj, name="Channel", code=f"channel-{company_obj.id if company_obj else 'global'}")


def schedule(company_obj, name="Schedule"):
    return Schedule.objects.create(company=company_obj, name=name, timezone="Europe/Madrid")


def policy(company_obj, **kwargs):
    return PlaybackPolicy.objects.create(company=company_obj, name="Policy", **kwargs)


def device(company_obj, code="dev"):
    return Device.objects.create(company=company_obj, hardware_id=f"hw-{code}", code=code, name=code, device_type=Device.DeviceType.DEDICATED_PLAYER)


def manifest(company_obj, zone_obj, version=1):
    return ContentManifest.objects.create(company=company_obj, zone=zone_obj, version=version, status=ContentManifest.Status.READY, generated_at=timezone.now(), checksum="abc")
