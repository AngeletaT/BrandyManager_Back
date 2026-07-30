from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from apps.audit.services import register_audit_log
from apps.billing.models import LicenseAssignment
from apps.billing.services import assign_license_to_zone
from apps.campaigns.models import Campaign
from apps.campaigns.services import campaign_is_active_at
from apps.catalog.models import AudioAsset, SongTag
from apps.devices.models import DeviceSync, DeviceZoneAssignment
from apps.devices.services import replace_zone_device, assign_device_to_zone
from apps.organizations.models import MembershipGrant, ResourceScope
from apps.playback.services import can_execute_playback_action, create_manifest
from apps.playlists.models import PlaylistSnapshot
from apps.playlists.services import publish_playlist
from apps.scheduling.models import ScheduleAssignment
from apps.scheduling.services import resolve_effective_schedule
from apps.organizations.tests import factories as f


class DatabaseRuleTests(TestCase):
    def setUp(self):
        self.company = f.company("acme")
        self.other_company = f.company("other")
        self.user = f.user("user@example.com")
        self.site = f.site(self.company)
        self.zone = f.zone(self.company, self.site)
        self.other_site = f.site(self.other_company, "other-site")
        self.other_zone = f.zone(self.other_company, self.other_site, "other-zone")

    def assert_invalid(self, callback):
        with self.assertRaises((ValidationError, IntegrityError)):
            with transaction.atomic():
                callback()

    def test_user_can_belong_to_multiple_companies(self):
        first = f.membership(self.company, self.user)
        second = f.membership(self.other_company, self.user)

        self.assertNotEqual(first.company_id, second.company_id)
        self.assertEqual(self.user.company_memberships.count(), 2)

    def test_membership_cannot_receive_custom_role_from_another_company(self):
        membership = f.membership(self.company, self.user)
        role = f.company_role(company_obj=self.other_company)
        scope = f.scope(self.company)

        self.assert_invalid(lambda: MembershipGrant.objects.create(membership=membership, role=role, scope=scope))

    def test_scope_cannot_reference_resource_from_another_company(self):
        self.assert_invalid(
            lambda: ResourceScope.objects.create(
                company=self.company,
                scope_type=ResourceScope.ScopeType.ZONE,
                zone=self.other_zone,
                name="bad",
            )
        )

    def test_license_cannot_be_assigned_to_zone_from_another_company(self):
        license_obj = f.license(self.company)

        self.assert_invalid(lambda: assign_license_to_zone(license_id=license_obj.id, zone=self.other_zone))

    def test_only_one_active_assignment_per_license(self):
        license_obj = f.license(self.company)
        assign_license_to_zone(license_id=license_obj.id, zone=self.zone)
        second_zone = f.zone(self.company, self.site, "second")

        self.assert_invalid(lambda: assign_license_to_zone(license_id=license_obj.id, zone=second_zone))

    def test_only_one_active_license_per_zone(self):
        assign_license_to_zone(license_id=f.license(self.company, "one").id, zone=self.zone)

        self.assert_invalid(lambda: assign_license_to_zone(license_id=f.license(self.company, "two").id, zone=self.zone))

    def test_device_can_be_replaced_without_modifying_zone_license(self):
        license_obj = f.license(self.company)
        license_assignment = assign_license_to_zone(license_id=license_obj.id, zone=self.zone)
        old_assignment = assign_device_to_zone(device=f.device(self.company, "old"), zone=self.zone)

        new_assignment = replace_zone_device(old_assignment=old_assignment, new_device=f.device(self.company, "new"))

        license_assignment.refresh_from_db()
        self.assertIsNone(license_assignment.unassigned_at)
        self.assertEqual(new_assignment.zone_id, self.zone.id)

    def test_only_one_primary_device_active_per_zone(self):
        assign_device_to_zone(device=f.device(self.company, "one"), zone=self.zone)

        self.assert_invalid(lambda: assign_device_to_zone(device=f.device(self.company, "two"), zone=self.zone))

    def test_song_has_no_artist_or_album_fields(self):
        song = f.song()

        field_names = {field.name for field in song._meta.fields}
        self.assertNotIn("artist", field_names)
        self.assertNotIn("album", field_names)

    def test_song_has_main_genre_and_multiple_tags(self):
        song = f.song()
        first_tag = f.tag()
        second_tag = f.tag(slug="elegant", name="Elegant")

        SongTag.objects.create(song=song, tag=first_tag)
        SongTag.objects.create(song=song, tag=second_tag)

        self.assertIsNotNone(song.genre)
        self.assertEqual(song.song_tags.count(), 2)

    def test_processed_asset_does_not_replace_original(self):
        song = f.song()
        original = f.asset(song.audio_content, role=AudioAsset.AssetRole.ORIGINAL, version=1, key="original", primary=False)
        processed = f.asset(song.audio_content, role=AudioAsset.AssetRole.NORMALIZED, version=1, key="normalized", primary=True)

        self.assertNotEqual(original.id, processed.id)
        self.assertTrue(AudioAsset.objects.filter(id=original.id).exists())

    def test_only_one_primary_ready_asset_per_content(self):
        song = f.song()
        f.asset(song.audio_content, role=AudioAsset.AssetRole.ORIGINAL, version=1, key="primary-1", primary=True)

        self.assert_invalid(lambda: f.asset(song.audio_content, role=AudioAsset.AssetRole.STREAM, version=1, key="primary-2", primary=True))

    def test_published_playlist_generates_immutable_snapshot(self):
        playlist = f.playlist_with_song(f.song())

        snapshot = publish_playlist(playlist=playlist)

        self.assertEqual(snapshot.status, PlaylistSnapshot.Status.PUBLISHED)
        self.assertEqual(snapshot.items.count(), 1)

    def test_device_uses_versioned_manifest(self):
        manifest = create_manifest(zone=self.zone, version=1, checksum="checksum", generated_at=timezone.now())

        self.assertEqual(manifest.version, 1)
        self.assertEqual(manifest.zone_id, self.zone.id)

    def test_effective_schedule_respects_priority_specificity_and_locks(self):
        company_scope = f.scope(self.company)
        zone_scope = f.scope(self.company, ResourceScope.ScopeType.ZONE, zone=self.zone)
        low = f.schedule(self.company, "low")
        high = f.schedule(self.company, "high")
        ScheduleAssignment.objects.create(company=self.company, schedule=low, scope=company_scope, priority=10, is_locked=True)
        ScheduleAssignment.objects.create(company=self.company, schedule=high, scope=zone_scope, priority=1)

        effective = resolve_effective_schedule(zone=self.zone)

        self.assertEqual(effective.schedule_id, low.id)

    def test_volume_limits_are_validated(self):
        self.assert_invalid(lambda: f.policy(self.company, minimum_volume=80, default_volume=60, maximum_volume=100))

    def test_permission_and_policy_are_checked_together(self):
        policy = f.policy(self.company, allow_pause=True)

        self.assertTrue(can_execute_playback_action(user_has_permission=True, policy=policy, action="pause"))
        self.assertFalse(can_execute_playback_action(user_has_permission=False, policy=policy, action="pause"))

    def test_campaign_is_not_active_outside_validity_period(self):
        now = timezone.now()
        campaign = Campaign.objects.create(
            company=self.company,
            name="Campaign",
            starts_at=now + timedelta(days=1),
            ends_at=now + timedelta(days=2),
            timezone="Europe/Madrid",
            created_by=self.user,
        )

        self.assertFalse(campaign_is_active_at(campaign=campaign, at=now))

    def test_device_cannot_sync_manifest_from_another_company(self):
        device = f.device(self.company)
        manifest = f.manifest(self.other_company, self.other_zone)

        self.assert_invalid(lambda: DeviceSync.objects.create(company=self.company, device=device, manifest=manifest))

    def test_audit_logs_are_not_modified_or_deleted(self):
        audit_log = register_audit_log(action="test", entity_type="Company", company=self.company)
        audit_log.action = "changed"

        self.assert_invalid(lambda: audit_log.save())
        self.assert_invalid(lambda: audit_log.delete())
