from datetime import timedelta

from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.authorization.models import CompanyRole, PlatformRole, UserPlatformRole
from apps.billing.services import create_trial_subscription
from apps.catalog.models import AudioContent, Genre, Song
from apps.organizations.models import CompanyMembership, MembershipGrant, ResourceScope, Site
from apps.organizations.tests import factories as f
from apps.playlists.models import Playlist, PlaylistItem, PlaylistSnapshot
from apps.playlists.services import publish_playlist
from apps.playback.models import ZoneOperationalSnapshot
from apps.scheduling.models import Schedule, ScheduleAssignment, ScheduleBlock, ScheduleException


class Phase3SchedulingAPITests(APITestCase):
    def setUp(self):
        call_command("seed_initial_data", verbosity=0)
        self.company = f.company("schedule-main")
        self.owner_user = self.verified_user("schedule-owner@example.com")
        self.owner_membership = self.add_member(self.owner_user, "OWNER")
        create_trial_subscription(company=self.company)
        self.site = f.site(self.company, "VALENCIA")
        self.zone = f.zone(self.company, self.site, "CAJAS")

    def verified_user(self, email):
        return f.User.objects.create_user(
            email=email,
            password="StrongPass123!",
            first_name="Schedule",
            last_name="User",
            email_verified_at=timezone.now(),
        )

    def scope(self, company=None, scope_type=ResourceScope.ScopeType.COMPANY, **kwargs):
        company = company or self.company
        scope, _ = ResourceScope.objects.get_or_create(
            company=company,
            scope_type=scope_type,
            defaults={"name": f"{scope_type} scope", "is_system_generated": True, **kwargs},
            **kwargs,
        )
        return scope

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

    def song(self, title="Schedule Song"):
        genre, _ = Genre.objects.get_or_create(slug="ambient", defaults={"name": "Ambient"})
        audio = AudioContent.objects.create(
            content_type=AudioContent.ContentType.SONG,
            title=title,
            internal_code=title.lower().replace(" ", "-"),
            visibility=AudioContent.Visibility.GLOBAL,
            status=AudioContent.Status.READY,
            is_active=True,
            duration_ms=180000,
            published_at=timezone.now(),
        )
        return Song.objects.create(audio_content=audio, genre=genre)

    def published_playlist(self, code="SCHED-PL"):
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

    def schedule(self, name="Semana Valencia"):
        return Schedule.objects.create(company=self.company, name=name, timezone="Europe/Madrid", created_by=self.owner_user)

    def assign_to_zone(self, schedule, priority=0):
        scope = self.scope(scope_type=ResourceScope.ScopeType.ZONE, zone=self.zone)
        return ScheduleAssignment.objects.create(company=self.company, schedule=schedule, scope=scope, priority=priority, assigned_by=self.owner_user)

    def add_block(self, schedule, playlist=None, start_time="10:00", end_time="12:00", priority=0):
        return ScheduleBlock.objects.create(
            schedule=schedule,
            day_of_week=0,
            start_time=start_time,
            end_time=end_time,
            content_type=ScheduleBlock.ContentType.PLAYLIST if playlist else ScheduleBlock.ContentType.SILENCE,
            playlist=playlist,
            priority=priority,
        )

    def test_authentication_required_and_internal_admin_denied(self):
        anonymous = self.client.get(reverse("schedule-list"))
        internal = self.verified_user("internal-schedule@example.com")
        UserPlatformRole.objects.create(user=internal, role=PlatformRole.objects.get(code="SUPPORT_AGENT"))
        self.authenticate(internal)
        internal_response = self.client.get(reverse("schedule-list"))

        self.assertEqual(anonymous.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(internal_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(internal_response.data["error"]["code"], "company_access_denied")

    def test_owner_and_editor_can_create_but_manager_and_viewer_only_read(self):
        for role_code, can_create in [("OWNER", True), ("EDITOR_PLAYLISTS", True), ("MANAGER", False), ("VIEWER", False)]:
            with self.subTest(role_code=role_code):
                user = self.verified_user(f"{role_code.lower()}-schedule@example.com")
                self.add_member(user, role_code)
                self.authenticate(user)

                list_response = self.client.get(reverse("schedule-list"))
                create_response = self.client.post(
                    reverse("schedule-list"),
                    {"name": f"{role_code} schedule", "timezone": "Europe/Madrid"},
                    format="json",
                )

                self.assertEqual(list_response.status_code, status.HTTP_200_OK)
                self.assertEqual(create_response.status_code, status.HTTP_201_CREATED if can_create else status.HTTP_403_FORBIDDEN)

    def test_create_rejects_company_and_status_payload(self):
        self.authenticate()

        response = self.client.post(
            reverse("schedule-list"),
            {"name": "Forbidden", "timezone": "Europe/Madrid", "company_id": str(self.company.id), "status": "PUBLISHED"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("company_id", response.data["error"]["fields"])
        self.assertIn("status", response.data["error"]["fields"])

    def test_crud_blocks_exceptions_assignments_and_publish(self):
        playlist = self.published_playlist()
        self.authenticate()
        created = self.client.post(reverse("schedule-list"), {"name": "Semana", "timezone": "Europe/Madrid"}, format="json")
        schedule_id = created.data["id"]
        revision = created.data["revision"]

        block_response = self.client.post(
            reverse("schedule-block-list", kwargs={"schedule_id": schedule_id}),
            {
                "expected_revision": revision,
                "day_of_week": 0,
                "start_time": "10:00:00",
                "end_time": "12:00:00",
                "content_type": "PLAYLIST",
                "playlist_id": str(playlist.id),
            },
            format="json",
        )
        revision = block_response.data["revision"]
        exception_response = self.client.post(
            reverse("schedule-exception-list", kwargs={"schedule_id": schedule_id}),
            {
                "expected_revision": revision,
                "date": "2026-09-07",
                "start_time": "10:30:00",
                "end_time": "11:00:00",
                "action": "SILENCE",
            },
            format="json",
        )
        revision = exception_response.data["revision"]
        assignment_response = self.client.post(
            reverse("schedule-assignment-list", kwargs={"schedule_id": schedule_id}),
            {"expected_revision": revision, "scope_type": "ZONE", "zone_id": str(self.zone.id), "priority": 5},
            format="json",
        )
        revision = assignment_response.data["revision"]
        publish_response = self.client.post(
            reverse("schedule-publish", kwargs={"schedule_id": schedule_id}),
            {"expected_revision": revision},
            format="json",
        )

        self.assertEqual(block_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(exception_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(assignment_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(publish_response.status_code, status.HTTP_200_OK)
        self.assertEqual(publish_response.data["status"], "PUBLISHED")
        self.assertEqual(publish_response.data["version"], 2)
        self.assertEqual(ScheduleBlock.objects.count(), 1)
        self.assertEqual(ScheduleException.objects.count(), 1)
        self.assertEqual(ScheduleAssignment.objects.count(), 1)
        operational = ZoneOperationalSnapshot.objects.get(zone=self.zone, status=ZoneOperationalSnapshot.Status.READY)
        self.assertEqual(str(operational.schedule_snapshot.schedule_id), schedule_id)
        self.assertEqual(operational.snapshot_data["schedule"]["snapshot_data"]["schedule_version"], 2)

    def test_block_validation_rejects_channel_midnight_and_unpublished_playlist(self):
        unpublished = Playlist.objects.create(owner_company=self.company, name="Draft", code="DRAFT", status=Playlist.Status.DRAFT)
        schedule = self.schedule()
        self.authenticate()

        channel = self.client.post(
            reverse("schedule-block-list", kwargs={"schedule_id": schedule.id}),
            {"expected_revision": schedule.revision, "day_of_week": 1, "start_time": "10:00", "end_time": "11:00", "content_type": "CHANNEL"},
            format="json",
        )
        midnight = self.client.post(
            reverse("schedule-block-list", kwargs={"schedule_id": schedule.id}),
            {"expected_revision": schedule.revision, "day_of_week": 1, "start_time": "23:00", "end_time": "01:00", "content_type": "SILENCE"},
            format="json",
        )
        unpublished_response = self.client.post(
            reverse("schedule-block-list", kwargs={"schedule_id": schedule.id}),
            {
                "expected_revision": schedule.revision,
                "day_of_week": 1,
                "start_time": "10:00",
                "end_time": "11:00",
                "content_type": "PLAYLIST",
                "playlist_id": str(unpublished.id),
            },
            format="json",
        )

        self.assertEqual(channel.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(midnight.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(unpublished_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(unpublished_response.data["error"]["code"], "schedule_content_unavailable")

    def test_overlap_same_priority_conflicts_but_higher_priority_resolves(self):
        schedule = self.schedule()
        self.add_block(schedule, start_time="10:00", end_time="12:00", priority=0)
        schedule.refresh_from_db()
        self.authenticate()

        conflict = self.client.post(
            reverse("schedule-block-list", kwargs={"schedule_id": schedule.id}),
            {"expected_revision": schedule.revision, "day_of_week": 0, "start_time": "11:00", "end_time": "13:00", "content_type": "SILENCE", "priority": 0},
            format="json",
        )
        schedule.refresh_from_db()
        allowed = self.client.post(
            reverse("schedule-block-list", kwargs={"schedule_id": schedule.id}),
            {"expected_revision": schedule.revision, "day_of_week": 0, "start_time": "11:00", "end_time": "13:00", "content_type": "SILENCE", "priority": 10},
            format="json",
        )

        self.assertEqual(conflict.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(conflict.data["error"]["code"], "schedule_conflict")
        self.assertEqual(allowed.status_code, status.HTTP_201_CREATED)

    def test_assignment_rejects_other_company_and_archived_destinations(self):
        schedule = self.schedule()
        other_company = f.company("schedule-other")
        other_site = f.site(other_company, "OTHER")
        archived_site = f.site(self.company, "ARCHIVED")
        archived_site.status = Site.Status.ARCHIVED
        archived_site.archived_at = timezone.now()
        archived_site.save(update_fields=["status", "archived_at", "updated_at"])
        self.authenticate()

        other_response = self.client.post(
            reverse("schedule-assignment-list", kwargs={"schedule_id": schedule.id}),
            {"expected_revision": schedule.revision, "scope_type": "SITE", "site_id": str(other_site.id)},
            format="json",
        )
        archived_response = self.client.post(
            reverse("schedule-assignment-list", kwargs={"schedule_id": schedule.id}),
            {"expected_revision": schedule.revision, "scope_type": "SITE", "site_id": str(archived_site.id)},
            format="json",
        )

        self.assertEqual(other_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(archived_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(other_response.data["error"]["code"], "schedule_assignment_invalid")

    def test_scoped_operator_can_read_assigned_schedule_but_not_mutate(self):
        schedule = self.schedule()
        self.assign_to_zone(schedule)
        zone_scope = self.scope(scope_type=ResourceScope.ScopeType.ZONE, zone=self.zone)
        operator = self.verified_user("operator-schedule@example.com")
        self.add_member(operator, "OPERADOR_SEDES", scope=zone_scope)
        self.authenticate(operator)

        list_response = self.client.get(reverse("schedule-list"))
        patch_response = self.client.patch(
            reverse("schedule-detail", kwargs={"schedule_id": schedule.id}),
            {"expected_revision": schedule.revision, "name": "Nope"},
            format="json",
        )

        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(list_response.data["count"], 1)
        self.assertEqual(patch_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_known_uuid_from_other_company_does_not_grant_access(self):
        other_company = f.company("schedule-hidden")
        hidden = Schedule.objects.create(company=other_company, name="Hidden", timezone="Europe/Madrid")
        self.authenticate()

        response = self.client.get(reverse("schedule-detail", kwargs={"schedule_id": hidden.id}))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["error"]["code"], "schedule_not_found")

    def test_resolution_uses_exception_and_reports_configuration_preview(self):
        playlist = self.published_playlist("RESOLVE")
        schedule = self.schedule()
        self.add_block(schedule, playlist=playlist, start_time="10:00", end_time="12:00")
        ScheduleException.objects.create(
            schedule=schedule,
            date="2026-09-07",
            start_time="10:30",
            end_time="11:00",
            action=ScheduleException.Action.SILENCE,
            priority=10,
        )
        self.assign_to_zone(schedule)
        publish_playlist(playlist=playlist, company=self.company, published_by=self.owner_user, expected_revision=playlist.revision)
        schedule.status = Schedule.Status.PUBLISHED
        schedule.published_at = timezone.now()
        schedule.save(update_fields=["status", "published_at", "updated_at"])
        self.authenticate()

        response = self.client.get(
            reverse("schedule-resolve"),
            {"zone_id": str(self.zone.id), "at": "2026-09-07T08:45:00Z"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["calculation_type"], "configuration_preview")
        self.assertFalse(response.data["execution_observed"])
        self.assertEqual(response.data["content"]["content_type"], "SILENCE")

    def test_resolution_without_applicable_block_returns_real_absence(self):
        schedule = self.schedule()
        self.assign_to_zone(schedule)
        schedule.status = Schedule.Status.PUBLISHED
        schedule.save(update_fields=["status", "updated_at"])
        self.authenticate()

        response = self.client.get(reverse("schedule-resolve"), {"zone_id": str(self.zone.id), "at": "2026-09-07T03:00:00Z"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["content"]["content_type"], "NONE")
        self.assertIsNone(response.data["content"]["playlist"])

    def test_next_occurrences_use_schedule_timezone_and_dst_safe_iso_output(self):
        schedule = self.schedule()
        self.add_block(schedule, start_time="02:30", end_time="03:30")
        self.authenticate()

        response = self.client.get(
            reverse("schedule-occurrences", kwargs={"schedule_id": schedule.id}),
            {"start_at": "2026-03-29T00:00:00Z", "days": 8, "limit": 2},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["calculation_type"], "configuration_preview")
        self.assertFalse(response.data["execution_observed"])
        self.assertGreaterEqual(len(response.data["results"]), 1)
        self.assertIn("starts_at", response.data["results"][0])

    def test_expired_trial_allows_read_but_blocks_mutation(self):
        subscription = self.company.subscriptions.get()
        subscription.trial_ends_at = timezone.now() - timedelta(days=1)
        subscription.current_period_end = subscription.trial_ends_at
        subscription.save(update_fields=["trial_ends_at", "current_period_end"])
        self.authenticate()

        list_response = self.client.get(reverse("schedule-list"))
        create_response = self.client.post(reverse("schedule-list"), {"name": "Blocked", "timezone": "Europe/Madrid"}, format="json")

        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(create_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(create_response.data["error"]["code"], "functional_access_blocked")

    def test_revision_conflict_and_assignment_deletion_is_logical(self):
        schedule = self.schedule()
        assignment = self.assign_to_zone(schedule)
        self.authenticate()

        patch = self.client.patch(
            reverse("schedule-detail", kwargs={"schedule_id": schedule.id}),
            {"expected_revision": schedule.revision, "name": "Updated"},
            format="json",
        )
        stale = self.client.patch(
            reverse("schedule-detail", kwargs={"schedule_id": schedule.id}),
            {"expected_revision": schedule.revision, "name": "Stale"},
            format="json",
        )
        schedule.refresh_from_db()
        delete_assignment = self.client.delete(
            reverse("schedule-assignment-detail", kwargs={"schedule_id": schedule.id, "assignment_id": assignment.id}),
            {"expected_revision": schedule.revision},
            format="json",
        )
        assignment.refresh_from_db()

        self.assertEqual(patch.status_code, status.HTTP_200_OK)
        self.assertEqual(stale.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(delete_assignment.status_code, status.HTTP_200_OK)
        self.assertFalse(assignment.is_active)

    def test_publish_does_not_create_channel_device_or_playback_effects(self):
        playlist = self.published_playlist("NO-EFFECT")
        schedule = self.schedule()
        self.add_block(schedule, playlist=playlist)
        self.assign_to_zone(schedule)
        self.authenticate()

        response = self.client.post(
            reverse("schedule-publish", kwargs={"schedule_id": schedule.id}),
            {"expected_revision": schedule.revision},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(PlaylistSnapshot.objects.filter(playlist=playlist).count(), 1)
        self.assertNotIn("execution_observed", response.data)
