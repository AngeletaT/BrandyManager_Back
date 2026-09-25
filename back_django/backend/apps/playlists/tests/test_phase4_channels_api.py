from datetime import time, timedelta

from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.authorization.models import CompanyRole, PlatformRole, UserPlatformRole
from apps.billing.services import create_trial_subscription
from apps.catalog.models import AudioAsset, AudioContent, Genre, Song
from apps.organizations.models import CompanyMembership, MembershipGrant, ResourceScope, Zone, ZoneChannelAssignment
from apps.organizations.tests import factories as f
from apps.playback.models import ZoneOperationalSnapshot
from apps.playlists.models import Channel, ChannelPlaylist, ChannelSnapshot, Playlist, PlaylistItem
from apps.playlists.services import publish_playlist
from apps.scheduling.models import Schedule, ScheduleBlock, ScheduleSnapshot
from apps.scheduling.services import publish_schedule


class Phase4ChannelsAPITests(APITestCase):
    def setUp(self):
        call_command("seed_initial_data", verbosity=0)
        self.company = f.company("channel-main")
        self.owner_user = self.verified_user("channel-owner@example.com")
        self.owner_membership = self.add_member(self.owner_user, "OWNER")
        create_trial_subscription(company=self.company)
        self.site = f.site(self.company, "VALENCIA")
        self.zone = f.zone(self.company, self.site, "CAJAS")

    def verified_user(self, email):
        return f.User.objects.create_user(
            email=email,
            password="StrongPass123!",
            first_name="Channel",
            last_name="User",
            email_verified_at=timezone.now(),
        )

    def scope(self, company=None, scope_type=ResourceScope.ScopeType.COMPANY, **kwargs):
        company = company or self.company
        return ResourceScope.objects.get_or_create(
            company=company,
            scope_type=scope_type,
            defaults={"name": f"{scope_type} scope", "is_system_generated": True, **kwargs},
            **kwargs,
        )[0]

    def add_member(self, user, role_code, company=None, scope=None):
        company = company or self.company
        membership = CompanyMembership.objects.create(
            company=company,
            user=user,
            status=CompanyMembership.Status.ACTIVE,
            accepted_at=timezone.now(),
        )
        role = CompanyRole.objects.get(company=None, code=role_code)
        MembershipGrant.objects.create(membership=membership, role=role, scope=scope or self.scope(company))
        return membership

    def authenticate(self, user=None):
        self.client.force_authenticate(user=user or self.owner_user)

    def song(self, title="Channel Song", *, duration_ms=180000):
        genre, _ = Genre.objects.get_or_create(slug="ambient", defaults={"name": "Ambient"})
        audio = AudioContent.objects.create(
            content_type=AudioContent.ContentType.SONG,
            title=title,
            internal_code=title.lower().replace(" ", "-"),
            visibility=AudioContent.Visibility.GLOBAL,
            status=AudioContent.Status.READY,
            is_active=True,
            duration_ms=duration_ms,
            published_at=timezone.now(),
        )
        AudioAsset.objects.create(
            audio_content=audio,
            asset_role=AudioAsset.AssetRole.STREAM,
            storage_backend="test",
            storage_key=f"{audio.internal_code}.mp3",
            original_filename=f"{audio.internal_code}.mp3",
            mime_type="audio/mpeg",
            container_format="mp3",
            codec="mp3",
            size_bytes=128,
            checksum_sha256="a" * 64,
            version=1,
            processing_status=AudioAsset.ProcessingStatus.READY,
            is_primary=True,
        )
        return Song.objects.create(audio_content=audio, genre=genre)

    def published_playlist(self, code="CH-PL"):
        playlist = Playlist.objects.create(
            owner_company=self.company,
            name=code,
            code=code,
            visibility=Playlist.Visibility.PRIVATE,
            status=Playlist.Status.DRAFT,
            created_by=self.owner_user,
        )
        PlaylistItem.objects.create(playlist=playlist, song=self.song(f"{code} Song"), position=1, weight=1)
        publish_playlist(playlist=playlist, company=self.company, published_by=self.owner_user, expected_revision=playlist.revision)
        playlist.refresh_from_db()
        return playlist

    def channel_with_playlist(self, code="CH"):
        playlist = self.published_playlist(f"{code}-PL")
        channel = Channel.objects.create(
            owner_company=self.company,
            name=code,
            code=code,
            visibility=Channel.Visibility.PRIVATE,
            status=Channel.Status.DRAFT,
            created_by=self.owner_user,
        )
        ChannelPlaylist.objects.create(channel=channel, playlist=playlist, weight=1, priority=0)
        return channel

    def publish_channel(self, channel):
        self.authenticate()
        response = self.client.post(
            reverse("channel-publish", kwargs={"channel_id": channel.id}),
            {"expected_revision": channel.revision},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        channel.refresh_from_db()
        return response

    def test_owner_and_manager_manage_channels_editor_and_viewer_only_read(self):
        for role_code, can_create in [("OWNER", True), ("MANAGER", True), ("EDITOR_PLAYLISTS", False), ("OPERADOR_SEDES", False), ("VIEWER", False)]:
            with self.subTest(role_code=role_code):
                user = self.verified_user(f"{role_code.lower()}-channel@example.com")
                scope = self.scope(scope_type=ResourceScope.ScopeType.ZONE, zone=self.zone) if role_code == "OPERADOR_SEDES" else self.scope()
                self.add_member(user, role_code, scope=scope)
                self.authenticate(user)

                list_response = self.client.get(reverse("channel-list"))
                create_response = self.client.post(
                    reverse("channel-list"),
                    {"name": f"{role_code} channel", "code": f"{role_code}-CH"},
                    format="json",
                )

                self.assertEqual(list_response.status_code, status.HTTP_200_OK)
                self.assertEqual(create_response.status_code, status.HTTP_201_CREATED if can_create else status.HTTP_403_FORBIDDEN)

    def test_internal_admin_cannot_use_client_channel_endpoints(self):
        internal = self.verified_user("internal-channel@example.com")
        UserPlatformRole.objects.create(user=internal, role=PlatformRole.objects.get(code="SUPPORT_AGENT"))
        self.authenticate(internal)

        response = self.client.get(reverse("channel-list"))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["error"]["code"], "company_access_denied")

    def test_create_rejects_company_id_and_uses_current_company(self):
        self.authenticate()

        forbidden = self.client.post(
            reverse("channel-list"),
            {"name": "Forbidden", "code": "FORBIDDEN", "company_id": str(self.company.id)},
            format="json",
        )
        response = self.client.post(reverse("channel-list"), {"name": "Created", "code": "created"}, format="json")

        self.assertEqual(forbidden.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("company_id", forbidden.data["error"]["fields"])
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        channel = Channel.objects.get(id=response.data["id"])
        self.assertEqual(channel.owner_company, self.company)
        self.assertEqual(channel.visibility, Channel.Visibility.PRIVATE)
        self.assertEqual(response.data["code"], "CREATED")

    def test_list_search_filter_order_and_pagination(self):
        Channel.objects.create(owner_company=self.company, name="Beta", code="BETA", status=Channel.Status.PUBLISHED)
        Channel.objects.create(owner_company=self.company, name="Alpha", code="ALPHA", status=Channel.Status.DRAFT)
        self.authenticate()

        response = self.client.get(
            reverse("channel-list"),
            {"search": "a", "status": "DRAFT", "ordering": "-name", "page": 1, "page_size": 1},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["code"], "ALPHA")
        self.assertTrue(response.data["permissions"]["can_create"])
        self.assertEqual(response.data["usage"]["used"], 2)
        self.assertEqual(response.data["usage"]["limit"], 6)

    def test_isolation_blocks_detail_and_assignment_of_other_company_resources(self):
        other_company = f.company("channel-other")
        other_user = self.verified_user("other-channel-owner@example.com")
        self.add_member(other_user, "OWNER", company=other_company, scope=self.scope(other_company))
        create_trial_subscription(company=other_company)
        other_site = f.site(other_company, "OTHER")
        other_zone = f.zone(other_company, other_site, "OTHER-ZONE")
        other_channel = Channel.objects.create(owner_company=other_company, name="Other", code="OTHER", status=Channel.Status.PUBLISHED)
        self.authenticate()

        detail = self.client.get(reverse("channel-detail", kwargs={"channel_id": other_channel.id}))
        assignment = self.client.put(
            reverse("channel-zone-assignment", kwargs={"zone_id": other_zone.id}),
            {"channel_id": str(other_channel.id)},
            format="json",
        )

        self.assertEqual(detail.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(assignment.status_code, status.HTTP_404_NOT_FOUND)

    def test_replace_playlists_publish_and_snapshot_is_immutable(self):
        first = self.published_playlist("FIRST")
        second = self.published_playlist("SECOND")
        self.authenticate()
        created = self.client.post(reverse("channel-list"), {"name": "Main", "code": "MAIN"}, format="json")
        channel_id = created.data["id"]

        config = self.client.put(
            reverse("channel-playlists", kwargs={"channel_id": channel_id}),
            {
                "expected_revision": created.data["revision"],
                "playlists": [
                    {"playlist_id": str(first.id), "weight": 1, "priority": 1},
                    {"playlist_id": str(second.id), "weight": 2, "priority": 0},
                ],
            },
            format="json",
        )
        publish = self.client.post(
            reverse("channel-publish", kwargs={"channel_id": channel_id}),
            {"expected_revision": config.data["revision"]},
            format="json",
        )
        snapshot_id = publish.data["snapshot"]["id"]
        channel = Channel.objects.get(id=channel_id)
        relation = channel.channel_playlists.get(playlist=first)
        relation.weight = 9
        relation.save(update_fields=["weight", "updated_at"])

        snapshot = ChannelSnapshot.objects.get(id=snapshot_id)

        self.assertEqual(config.status_code, status.HTTP_200_OK)
        self.assertEqual(publish.status_code, status.HTTP_201_CREATED)
        self.assertEqual(snapshot.playlists.count(), 2)
        self.assertEqual(snapshot.playlists.get(playlist=first).weight, 1)
        self.assertEqual(channel.current_version, 1)

    def test_publish_is_idempotent_for_same_configuration(self):
        channel = self.channel_with_playlist("IDEMP")
        first = self.publish_channel(channel)
        channel.refresh_from_db()
        second = self.client.post(
            reverse("channel-publish", kwargs={"channel_id": channel.id}),
            {"expected_revision": channel.revision},
            format="json",
        )

        self.assertEqual(second.status_code, status.HTTP_201_CREATED)
        self.assertEqual(first.data["snapshot"]["id"], second.data["snapshot"]["id"])
        self.assertEqual(ChannelSnapshot.objects.filter(channel=channel).count(), 1)

    def test_revision_conflict_blocks_stale_update(self):
        channel = self.channel_with_playlist("REV")
        self.authenticate()

        first = self.client.patch(
            reverse("channel-detail", kwargs={"channel_id": channel.id}),
            {"expected_revision": channel.revision, "name": "First"},
            format="json",
        )
        second = self.client.patch(
            reverse("channel-detail", kwargs={"channel_id": channel.id}),
            {"expected_revision": channel.revision, "name": "Second"},
            format="json",
        )

        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(second.data["error"]["code"], "channel_revision_conflict")

    def test_assign_change_and_unassign_channel_to_zone_create_operational_snapshots(self):
        first = self.channel_with_playlist("ASSIGN-A")
        second = self.channel_with_playlist("ASSIGN-B")
        self.publish_channel(first)
        self.publish_channel(second)

        assign = self.client.put(
            reverse("channel-zone-assignment", kwargs={"zone_id": self.zone.id}),
            {"channel_id": str(first.id), "reason": "Initial"},
            format="json",
        )
        change = self.client.put(
            reverse("channel-zone-assignment", kwargs={"zone_id": self.zone.id}),
            {"channel_id": str(second.id), "reason": "Change"},
            format="json",
        )
        remove = self.client.delete(
            reverse("channel-zone-assignment", kwargs={"zone_id": self.zone.id}),
            {"reason": "Stop"},
            format="json",
        )

        self.assertEqual(assign.status_code, status.HTTP_200_OK)
        self.assertEqual(change.status_code, status.HTTP_200_OK)
        self.assertEqual(remove.status_code, status.HTTP_200_OK)
        self.assertFalse(ZoneChannelAssignment.objects.filter(zone=self.zone, unassigned_at__isnull=True).exists())
        self.assertEqual(ZoneOperationalSnapshot.objects.filter(zone=self.zone).count(), 3)
        latest = ZoneOperationalSnapshot.objects.filter(zone=self.zone).latest("generated_at")
        self.assertFalse(latest.snapshot_data["execution_observed"])
        self.assertIsNone(latest.channel_snapshot_id)

    def test_operator_can_assign_only_scoped_zone(self):
        channel = self.channel_with_playlist("SCOPED")
        self.publish_channel(channel)
        other_site = f.site(self.company, "MADRID")
        other_zone = f.zone(self.company, other_site, "BARRA")
        operator = self.verified_user("operator-channel@example.com")
        self.add_member(operator, "OPERADOR_SEDES", scope=self.scope(scope_type=ResourceScope.ScopeType.ZONE, zone=self.zone))
        self.authenticate(operator)

        allowed = self.client.put(
            reverse("channel-zone-assignment", kwargs={"zone_id": self.zone.id}),
            {"channel_id": str(channel.id)},
            format="json",
        )
        denied = self.client.put(
            reverse("channel-zone-assignment", kwargs={"zone_id": other_zone.id}),
            {"channel_id": str(channel.id)},
            format="json",
        )

        self.assertEqual(allowed.status_code, status.HTTP_200_OK)
        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN)

    def test_archived_zone_or_channel_cannot_be_assigned(self):
        channel = self.channel_with_playlist("ARCH-ASSIGN")
        self.publish_channel(channel)
        self.zone.status = Zone.Status.ARCHIVED
        self.zone.archived_at = timezone.now()
        self.zone.save(update_fields=["status", "archived_at", "updated_at"])

        response = self.client.put(
            reverse("channel-zone-assignment", kwargs={"zone_id": self.zone.id}),
            {"channel_id": str(channel.id)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"]["code"], "zone_channel_assignment_invalid")

    def test_archive_blocks_assigned_channel_and_reactivate_validates_limit(self):
        channel = self.channel_with_playlist("ARCHIVE")
        self.publish_channel(channel)
        self.client.put(reverse("channel-zone-assignment", kwargs={"zone_id": self.zone.id}), {"channel_id": str(channel.id)}, format="json")
        channel.refresh_from_db()

        archive_assigned = self.client.post(
            reverse("channel-archive", kwargs={"channel_id": channel.id}),
            {"expected_revision": channel.revision},
            format="json",
        )
        self.client.delete(reverse("channel-zone-assignment", kwargs={"zone_id": self.zone.id}), {}, format="json")
        channel.refresh_from_db()
        archive = self.client.post(reverse("channel-archive", kwargs={"channel_id": channel.id}), {"expected_revision": channel.revision}, format="json")

        self.assertEqual(archive_assigned.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(archive_assigned.data["error"]["code"], "channel_in_use")
        self.assertEqual(archive.status_code, status.HTTP_200_OK)
        self.assertEqual(archive.data["status"], "ARCHIVED")

    def test_channel_plan_limit_blocks_create_and_duplicate(self):
        self.authenticate()
        for index in range(6):
            response = self.client.post(reverse("channel-list"), {"name": f"Ch {index}", "code": f"CH-{index}"}, format="json")
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        create_over_limit = self.client.post(reverse("channel-list"), {"name": "Over", "code": "OVER"}, format="json")
        duplicate_over_limit = self.client.post(
            reverse("channel-duplicate", kwargs={"channel_id": Channel.objects.filter(owner_company=self.company).first().id}),
            {},
            format="json",
        )

        self.assertEqual(create_over_limit.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(create_over_limit.data["error"]["code"], "channel_limit_reached")
        self.assertEqual(duplicate_over_limit.status_code, status.HTTP_403_FORBIDDEN)

    def test_expired_trial_blocks_functional_channel_endpoint(self):
        expired_company = f.company("channel-expired")
        expired_user = self.verified_user("expired-channel@example.com")
        self.add_member(expired_user, "OWNER", company=expired_company, scope=self.scope(expired_company))
        create_trial_subscription(company=expired_company, starts_at=timezone.now() - timedelta(days=8))
        self.authenticate(expired_user)

        response = self.client.get(reverse("channel-list"))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["error"]["code"], "functional_access_blocked")

    def test_schedule_publish_creates_immutable_schedule_snapshot(self):
        playlist = self.published_playlist("SCHEDULE-PL")
        schedule = Schedule.objects.create(company=self.company, name="Morning", timezone="Europe/Madrid", created_by=self.owner_user)
        ScheduleBlock.objects.create(
            schedule=schedule,
            day_of_week=0,
            start_time="09:00",
            end_time="10:00",
            content_type=ScheduleBlock.ContentType.PLAYLIST,
            playlist=playlist,
        )

        publish_schedule(schedule=schedule, expected_revision=schedule.revision, published_by=self.owner_user)
        schedule.refresh_from_db()
        block = schedule.blocks.get()
        block.start_time = time(9, 30)
        block.save(update_fields=["start_time", "updated_at"])

        snapshot = ScheduleSnapshot.objects.get(schedule=schedule)

        self.assertEqual(snapshot.version, schedule.version)
        self.assertEqual(snapshot.snapshot_data["blocks"][0]["start_time"], "09:00:00")
        self.assertEqual(snapshot.snapshot_data["blocks"][0]["playlist_snapshot_version"], playlist.current_version)
