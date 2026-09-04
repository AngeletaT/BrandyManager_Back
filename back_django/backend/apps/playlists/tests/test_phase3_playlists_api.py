from datetime import timedelta

from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.authorization.models import CompanyRole, PlatformRole, UserPlatformRole
from apps.billing.services import create_trial_subscription
from apps.catalog.models import AudioContent, Genre, Song, SongTag, Tag, TagCategory
from apps.organizations.models import CompanyMembership, MembershipGrant, ResourceScope
from apps.organizations.tests import factories as f
from apps.playlists.models import Channel, ContentAccessGrant, Playlist, PlaylistItem, PlaylistSnapshot
from apps.scheduling.models import Schedule, ScheduleBlock


class Phase3PlaylistsAPITests(APITestCase):
    def setUp(self):
        call_command("seed_initial_data", verbosity=0)
        self.company = f.company("playlist-main")
        self.owner_user = self.verified_user("playlist-owner@example.com")
        self.owner_membership = self.add_member(self.owner_user, "OWNER")
        create_trial_subscription(company=self.company)

    def verified_user(self, email):
        return f.User.objects.create_user(
            email=email,
            password="StrongPass123!",
            first_name="Playlist",
            last_name="User",
            email_verified_at=timezone.now(),
        )

    def company_scope(self, company=None):
        company = company or self.company
        scope, _ = ResourceScope.objects.get_or_create(
            company=company,
            scope_type=ResourceScope.ScopeType.COMPANY,
            defaults={"name": f"{company.trade_name} scope", "is_system_generated": True},
        )
        return scope

    def add_member(self, user, role_code, company=None):
        company = company or self.company
        membership = CompanyMembership.objects.create(
            company=company,
            user=user,
            status=CompanyMembership.Status.ACTIVE,
            accepted_at=timezone.now(),
        )
        role = CompanyRole.objects.get(company=None, code=role_code)
        MembershipGrant.objects.create(membership=membership, role=role, scope=self.company_scope(company))
        return membership

    def authenticate(self, user=None):
        self.client.force_authenticate(user=user or self.owner_user)

    def genre(self, slug="lo-fi", name="Lo-fi"):
        return Genre.objects.get_or_create(slug=slug, defaults={"name": name})[0]

    def tag(self, slug="relajado", name="Relajado"):
        category, _ = TagCategory.objects.get_or_create(code="MOOD", defaults={"name": "Mood"})
        return Tag.objects.get_or_create(category=category, slug=slug, defaults={"name": name})[0]

    def song(
        self,
        title="Song",
        *,
        internal_code=None,
        company=None,
        visibility=AudioContent.Visibility.GLOBAL,
        status_value=AudioContent.Status.READY,
        duration_ms=180000,
        tags=None,
    ):
        audio = AudioContent.objects.create(
            owner_company=company,
            content_type=AudioContent.ContentType.SONG,
            title=title,
            internal_code=internal_code or title.lower().replace(" ", "-"),
            visibility=visibility,
            status=status_value,
            is_active=True,
            duration_ms=duration_ms,
            published_at=timezone.now() if status_value == AudioContent.Status.READY else None,
        )
        song = Song.objects.create(audio_content=audio, genre=self.genre())
        for tag in tags or []:
            SongTag.objects.create(song=song, tag=tag)
        return song

    def playlist(self, *, company=None, code="PL", status_value=Playlist.Status.DRAFT, songs=None):
        playlist = Playlist.objects.create(
            owner_company=company if company is not None else self.company,
            name=code,
            code=code,
            description="Playlist description",
            playlist_type=Playlist.PlaylistType.MANUAL,
            visibility=Playlist.Visibility.PRIVATE,
            status=status_value,
            created_by=self.owner_user,
        )
        for position, song in enumerate(songs or [], start=1):
            PlaylistItem.objects.create(playlist=playlist, song=song, position=position, weight=1)
        return playlist

    def test_owner_and_editor_can_create_playlist_but_manager_and_viewer_only_read(self):
        for role_code, can_create in [("OWNER", True), ("EDITOR_PLAYLISTS", True), ("MANAGER", False), ("VIEWER", False)]:
            with self.subTest(role_code=role_code):
                user = self.verified_user(f"{role_code.lower()}-playlist@example.com")
                self.add_member(user, role_code)
                self.authenticate(user)

                list_response = self.client.get(reverse("playlist-list"))
                create_response = self.client.post(
                    reverse("playlist-list"),
                    {"name": f"{role_code} playlist", "code": f"{role_code}-PL"},
                    format="json",
                )

                self.assertEqual(list_response.status_code, status.HTTP_200_OK)
                self.assertEqual(create_response.status_code, status.HTTP_201_CREATED if can_create else status.HTTP_403_FORBIDDEN)

    def test_internal_admin_cannot_use_client_playlist_endpoints(self):
        internal = self.verified_user("internal-playlist@example.com")
        platform_role = PlatformRole.objects.get(code="SUPPORT_AGENT")
        UserPlatformRole.objects.create(user=internal, role=platform_role)
        self.authenticate(internal)

        response = self.client.get(reverse("playlist-list"))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["error"]["code"], "company_access_denied")

    def test_create_rejects_company_id_and_uses_current_company(self):
        self.authenticate()

        forbidden = self.client.post(
            reverse("playlist-list"),
            {"name": "Forbidden", "code": "FORBIDDEN", "company_id": str(self.company.id)},
            format="json",
        )
        response = self.client.post(reverse("playlist-list"), {"name": "Created", "code": "created"}, format="json")

        self.assertEqual(forbidden.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("company_id", forbidden.data["error"]["fields"])
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        playlist = Playlist.objects.get(id=response.data["id"])
        self.assertEqual(playlist.owner_company, self.company)
        self.assertEqual(playlist.visibility, Playlist.Visibility.PRIVATE)
        self.assertEqual(response.data["code"], "CREATED")

    def test_list_search_filter_order_and_pagination(self):
        self.playlist(code="BETA", status_value=Playlist.Status.PUBLISHED)
        self.playlist(code="ALPHA", status_value=Playlist.Status.DRAFT)
        self.authenticate()

        response = self.client.get(
            reverse("playlist-list"),
            {"search": "a", "status": "DRAFT", "ordering": "-name", "page": 1, "page_size": 1},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["page_size"], 1)
        self.assertEqual(response.data["results"][0]["code"], "ALPHA")

    def test_isolation_blocks_detail_and_update_of_other_company_playlist(self):
        other_company = f.company("playlist-other")
        other_playlist = self.playlist(company=other_company, code="OTHER")
        self.authenticate()

        detail = self.client.get(reverse("playlist-detail", kwargs={"playlist_id": other_playlist.id}))
        patch = self.client.patch(
            reverse("playlist-detail", kwargs={"playlist_id": other_playlist.id}),
            {"expected_revision": other_playlist.revision, "name": "Nope"},
            format="json",
        )

        self.assertEqual(detail.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(patch.status_code, status.HTTP_404_NOT_FOUND)

    def test_add_remove_replace_and_reorder_items_preserve_consistent_positions(self):
        first = self.song("First")
        second = self.song("Second")
        third = self.song("Third")
        playlist = self.playlist(code="ORDER", songs=[first])
        self.authenticate()

        add_response = self.client.post(
            reverse("playlist-item-list", kwargs={"playlist_id": playlist.id}),
            {"expected_revision": playlist.revision, "song_id": str(second.id), "weight": 2},
            format="json",
        )
        playlist.refresh_from_db()
        replace_response = self.client.put(
            reverse("playlist-item-list", kwargs={"playlist_id": playlist.id}),
            {
                "expected_revision": playlist.revision,
                "items": [
                    {"song_id": str(first.id), "position": 1, "weight": 1},
                    {"song_id": str(second.id), "position": 2, "weight": 1},
                    {"song_id": str(third.id), "position": 3, "weight": 1},
                ],
            },
            format="json",
        )
        playlist.refresh_from_db()
        item_ids = [item["id"] for item in replace_response.data["items"]]
        reorder_response = self.client.put(
            reverse("playlist-item-order", kwargs={"playlist_id": playlist.id}),
            {"expected_revision": playlist.revision, "item_ids": list(reversed(item_ids))},
            format="json",
        )
        playlist.refresh_from_db()
        delete_response = self.client.delete(
            reverse("playlist-item-detail", kwargs={"playlist_id": playlist.id, "item_id": reorder_response.data["items"][0]["id"]}),
            {"expected_revision": playlist.revision},
            format="json",
        )

        self.assertEqual(add_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(replace_response.status_code, status.HTTP_200_OK)
        self.assertEqual(reorder_response.status_code, status.HTTP_200_OK)
        self.assertEqual(delete_response.status_code, status.HTTP_200_OK)
        self.assertEqual([item["position"] for item in delete_response.data["items"]], [1, 2])

    def test_reorder_rejects_missing_foreign_or_repeated_items(self):
        first = self.song("Reorder First")
        playlist = self.playlist(code="BADORDER", songs=[first])
        other_playlist = self.playlist(code="OTHERORDER", songs=[first])
        item = playlist.items.get()
        other_item = other_playlist.items.get()
        self.authenticate()

        repeated = self.client.put(
            reverse("playlist-item-order", kwargs={"playlist_id": playlist.id}),
            {"expected_revision": playlist.revision, "item_ids": [str(item.id), str(item.id)]},
            format="json",
        )
        foreign = self.client.put(
            reverse("playlist-item-order", kwargs={"playlist_id": playlist.id}),
            {"expected_revision": playlist.revision, "item_ids": [str(item.id), str(other_item.id)]},
            format="json",
        )

        self.assertEqual(repeated.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(foreign.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(foreign.data["error"]["code"], "playlist_order_conflict")

    def test_same_song_can_appear_multiple_times(self):
        song = self.song("Repeated")
        playlist = self.playlist(code="REPEAT")
        self.authenticate()

        first = self.client.post(
            reverse("playlist-item-list", kwargs={"playlist_id": playlist.id}),
            {"expected_revision": playlist.revision, "song_id": str(song.id)},
            format="json",
        )
        playlist.refresh_from_db()
        second = self.client.post(
            reverse("playlist-item-list", kwargs={"playlist_id": playlist.id}),
            {"expected_revision": playlist.revision, "song_id": str(song.id)},
            format="json",
        )

        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(second.data["items"]), 2)
        self.assertNotEqual(second.data["items"][0]["id"], second.data["items"][1]["id"])

    def test_cannot_add_private_content_from_other_company_but_can_add_granted_shared_content(self):
        other_company = f.company("playlist-song-other")
        private_song = self.song(
            "Private other",
            internal_code="private-other",
            company=other_company,
            visibility=AudioContent.Visibility.PRIVATE,
        )
        shared_song = self.song(
            "Shared other",
            internal_code="shared-other",
            company=other_company,
            visibility=AudioContent.Visibility.SHARED,
        )
        ContentAccessGrant.objects.create(company=self.company, audio_content=shared_song.audio_content, granted_at=timezone.now())
        playlist = self.playlist(code="CONTENT")
        self.authenticate()

        private_response = self.client.post(
            reverse("playlist-item-list", kwargs={"playlist_id": playlist.id}),
            {"expected_revision": playlist.revision, "song_id": str(private_song.id)},
            format="json",
        )
        playlist.refresh_from_db()
        shared_response = self.client.post(
            reverse("playlist-item-list", kwargs={"playlist_id": playlist.id}),
            {"expected_revision": playlist.revision, "song_id": str(shared_song.id)},
            format="json",
        )

        self.assertEqual(private_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(private_response.data["error"]["code"], "playlist_content_unavailable")
        self.assertEqual(shared_response.status_code, status.HTTP_201_CREATED)

    def test_quota_blocks_create_duplicate_and_reactivate(self):
        subscription = self.company.subscriptions.get()
        subscription.plan_snapshot["limits"]["playlists"] = 1
        subscription.save(update_fields=["plan_snapshot"])
        existing = self.playlist(code="EXISTING")
        archived = self.playlist(code="ARCHIVED", status_value=Playlist.Status.ARCHIVED)
        archived.archived_at = timezone.now()
        archived.save(update_fields=["archived_at", "updated_at"])
        self.authenticate()

        create_response = self.client.post(reverse("playlist-list"), {"name": "Second", "code": "SECOND"}, format="json")
        duplicate_response = self.client.post(reverse("playlist-duplicate", kwargs={"playlist_id": existing.id}), {}, format="json")
        reactivate_response = self.client.post(
            reverse("playlist-reactivate", kwargs={"playlist_id": archived.id}),
            {"expected_revision": archived.revision},
            format="json",
        )

        self.assertEqual(create_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(duplicate_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(reactivate_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(create_response.data["error"]["code"], "playlist_limit_reached")

    def test_revision_conflict_blocks_stale_metadata_update(self):
        playlist = self.playlist(code="REVISION")
        self.authenticate()

        first = self.client.patch(
            reverse("playlist-detail", kwargs={"playlist_id": playlist.id}),
            {"expected_revision": playlist.revision, "name": "First update"},
            format="json",
        )
        stale = self.client.patch(
            reverse("playlist-detail", kwargs={"playlist_id": playlist.id}),
            {"expected_revision": playlist.revision, "name": "Stale update"},
            format="json",
        )

        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(stale.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(stale.data["error"]["code"], "playlist_revision_conflict")

    def test_publish_creates_immutable_snapshot_and_repeated_publish_is_idempotent(self):
        first = self.song("Snapshot First")
        second = self.song("Snapshot Second")
        third = self.song("Snapshot Third")
        playlist = self.playlist(code="PUBLISH", songs=[first, second])
        self.authenticate()

        publish_response = self.client.post(
            reverse("playlist-publish", kwargs={"playlist_id": playlist.id}),
            {"expected_revision": playlist.revision},
            format="json",
        )
        repeated_response = self.client.post(
            reverse("playlist-publish", kwargs={"playlist_id": playlist.id}),
            {"expected_revision": playlist.revision},
            format="json",
        )
        playlist.refresh_from_db()
        add_response = self.client.post(
            reverse("playlist-item-list", kwargs={"playlist_id": playlist.id}),
            {"expected_revision": playlist.revision, "song_id": str(third.id)},
            format="json",
        )

        self.assertEqual(publish_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(repeated_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(PlaylistSnapshot.objects.filter(playlist=playlist).count(), 1)
        snapshot = PlaylistSnapshot.objects.get(playlist=playlist)
        self.assertEqual(snapshot.items.count(), 2)
        self.assertEqual(add_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(snapshot.items.count(), 2)

    def test_published_version_endpoint_returns_latest_snapshot(self):
        song = self.song("Published Version")
        playlist = self.playlist(code="VERSION", songs=[song])
        self.authenticate()
        self.client.post(reverse("playlist-publish", kwargs={"playlist_id": playlist.id}), {"expected_revision": playlist.revision}, format="json")

        response = self.client.get(reverse("playlist-published-version", kwargs={"playlist_id": playlist.id}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["snapshot"]["version"], 1)

    def test_publish_empty_playlist_fails_without_minimum_duration_rule(self):
        playlist = self.playlist(code="EMPTY")
        self.authenticate()

        response = self.client.post(
            reverse("playlist-publish", kwargs={"playlist_id": playlist.id}),
            {"expected_revision": playlist.revision},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"]["code"], "playlist_not_publishable")

    def test_unknown_duration_is_null_not_zero(self):
        song = self.song("Unknown duration", duration_ms=None)
        playlist = self.playlist(code="UNKNOWNDURATION", songs=[song])
        self.authenticate()

        response = self.client.get(reverse("playlist-detail", kwargs={"playlist_id": playlist.id}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data["duration_ms"])

    def test_detail_returns_real_schedule_usage_and_archive_blocks_used_playlist(self):
        song = self.song("Used Song")
        playlist = self.playlist(code="USED", songs=[song])
        schedule = Schedule.objects.create(company=self.company, name="Schedule", timezone="Europe/Madrid")
        ScheduleBlock.objects.create(
            schedule=schedule,
            day_of_week=0,
            start_time="10:00",
            end_time="12:00",
            content_type=ScheduleBlock.ContentType.PLAYLIST,
            playlist=playlist,
        )
        self.authenticate()

        detail_response = self.client.get(reverse("playlist-detail", kwargs={"playlist_id": playlist.id}))
        archive_response = self.client.post(
            reverse("playlist-archive", kwargs={"playlist_id": playlist.id}),
            {"expected_revision": playlist.revision},
            format="json",
        )

        self.assertEqual(detail_response.status_code, status.HTTP_200_OK)
        self.assertEqual(detail_response.data["usage"][0]["schedule"]["id"], str(schedule.id))
        self.assertEqual(archive_response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(archive_response.data["error"]["code"], "playlist_in_use")

    def test_expired_trial_blocks_playlist_endpoints(self):
        subscription = self.company.subscriptions.get()
        subscription.trial_ends_at = timezone.now() - timedelta(days=1)
        subscription.current_period_end = subscription.trial_ends_at
        subscription.save(update_fields=["trial_ends_at", "current_period_end"])
        self.authenticate()

        response = self.client.get(reverse("playlist-list"))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["error"]["code"], "functional_access_blocked")

    def test_publish_has_no_playback_side_effects(self):
        song = self.song("No Playback")
        playlist = self.playlist(code="NOPLAYBACK", songs=[song])
        self.authenticate()

        response = self.client.post(
            reverse("playlist-publish", kwargs={"playlist_id": playlist.id}),
            {"expected_revision": playlist.revision},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Channel.objects.count(), 0)
