from datetime import timedelta

from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.authorization.models import CompanyRole, PlatformRole, UserPlatformRole
from apps.billing.services import create_trial_subscription
from apps.catalog.models import AudioAsset, AudioContent, Genre, Song, SongTag, Tag, TagCategory
from apps.organizations.models import Company, CompanyMembership, MembershipGrant, ResourceScope
from apps.organizations.tests import factories as f
from apps.playlists.models import ContentAccessGrant


class Phase3CatalogAPITests(APITestCase):
    def setUp(self):
        call_command("seed_initial_data", verbosity=0)
        self.company = f.company("catalog-main")
        self.owner_user = self.verified_user("catalog-owner@example.com")
        self.owner_membership = self.add_member(self.owner_user, "OWNER")
        create_trial_subscription(company=self.company)

    def verified_user(self, email):
        return f.User.objects.create_user(
            email=email,
            password="StrongPass123!",
            first_name="Catalog",
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

    def genre(self, slug, name):
        return Genre.objects.get_or_create(slug=slug, defaults={"name": name})[0]

    def tag(self, *, category_code, category_name, slug, name):
        category, _ = TagCategory.objects.get_or_create(
            code=category_code,
            defaults={"name": category_name, "sort_order": 1},
        )
        return Tag.objects.get_or_create(category=category, slug=slug, defaults={"name": name})[0]

    def song(
        self,
        *,
        title,
        internal_code,
        company=None,
        visibility=AudioContent.Visibility.GLOBAL,
        status_value=AudioContent.Status.READY,
        is_active=True,
        genre=None,
        tags=None,
        duration_ms=None,
    ):
        audio_content = AudioContent.objects.create(
            owner_company=company,
            content_type=AudioContent.ContentType.SONG,
            title=title,
            internal_code=internal_code,
            description=f"{title} description",
            visibility=visibility,
            status=status_value,
            duration_ms=duration_ms,
            is_active=is_active,
            published_at=timezone.now() if status_value == AudioContent.Status.READY else None,
        )
        song = Song.objects.create(
            audio_content=audio_content,
            genre=genre or self.genre("lo-fi", "Lo-fi"),
            is_explicit=False,
        )
        for tag in tags or []:
            SongTag.objects.create(song=song, tag=tag)
        return song

    def add_asset(self, song, *, role=AudioAsset.AssetRole.PREVIEW, processing_status=AudioAsset.ProcessingStatus.READY, version=1):
        return AudioAsset.objects.create(
            audio_content=song.audio_content,
            asset_role=role,
            storage_backend="s3",
            storage_key=f"private/{song.id}/{role}/{processing_status}/{version}",
            original_filename="track.mp3",
            mime_type="audio/mpeg",
            container_format="mp3",
            codec="mp3",
            size_bytes=1000,
            duration_ms=30000,
            checksum_sha256="a" * 64,
            version=version,
            processing_status=processing_status,
            is_primary=role == AudioAsset.AssetRole.PREVIEW and processing_status == AudioAsset.ProcessingStatus.READY,
        )

    def test_authentication_is_required(self):
        response = self.client.get(reverse("catalog-song-list"))

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_roles_with_catalog_permission_can_list_available_songs(self):
        for role_code in ["OWNER", "MANAGER", "EDITOR_PLAYLISTS", "VIEWER"]:
            with self.subTest(role_code=role_code):
                user = self.verified_user(f"{role_code.lower()}-catalog@example.com")
                self.add_member(user, role_code)
                self.client.force_authenticate(user=user)

                response = self.client.get(reverse("catalog-song-list"))

                self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_operator_without_catalog_permission_cannot_list_songs(self):
        user = self.verified_user("operator-catalog@example.com")
        self.add_member(user, "OPERADOR_SEDES")
        self.authenticate(user)

        response = self.client.get(reverse("catalog-song-list"))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["error"]["code"], "permission_denied")

    def test_internal_admin_cannot_use_client_catalog(self):
        internal = self.verified_user("internal-catalog@example.com")
        platform_role = PlatformRole.objects.get(code="SUPPORT_AGENT")
        UserPlatformRole.objects.create(user=internal, role=platform_role)
        self.authenticate(internal)

        response = self.client.get(reverse("catalog-song-list"))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["error"]["code"], "company_access_denied")

    def test_list_includes_only_global_own_private_and_granted_shared_content(self):
        other_company = f.company("catalog-other")
        global_song = self.song(title="Global ready", internal_code="global-ready")
        own_private = self.song(
            title="Own private",
            internal_code="own-private",
            company=self.company,
            visibility=AudioContent.Visibility.PRIVATE,
        )
        granted_shared = self.song(
            title="Granted shared",
            internal_code="granted-shared",
            company=other_company,
            visibility=AudioContent.Visibility.SHARED,
        )
        ContentAccessGrant.objects.create(
            company=self.company,
            audio_content=granted_shared.audio_content,
            granted_at=timezone.now(),
        )
        self.song(
            title="Other private",
            internal_code="other-private",
            company=other_company,
            visibility=AudioContent.Visibility.PRIVATE,
        )
        self.song(
            title="Other ungranted shared",
            internal_code="other-ungranted",
            company=other_company,
            visibility=AudioContent.Visibility.SHARED,
        )
        self.song(title="Draft global", internal_code="draft-global", status_value=AudioContent.Status.DRAFT)
        self.song(title="Inactive global", internal_code="inactive-global", is_active=False)
        self.authenticate()

        response = self.client.get(reverse("catalog-song-list"), {"ordering": "title"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        titles = [item["title"] for item in response.data["results"]]
        self.assertEqual(titles, ["Global ready", "Granted shared", "Own private"])
        self.assertEqual({item["id"] for item in response.data["results"]}, {str(global_song.id), str(own_private.id), str(granted_shared.id)})

    def test_known_uuid_does_not_grant_detail_access(self):
        other_company = f.company("catalog-hidden")
        hidden = self.song(
            title="Hidden private",
            internal_code="hidden-private",
            company=other_company,
            visibility=AudioContent.Visibility.PRIVATE,
        )
        self.authenticate()

        response = self.client.get(reverse("catalog-song-detail", kwargs={"song_id": hidden.id}))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["error"]["code"], "catalog_song_not_found")

    def test_pagination_search_filters_and_ordering_are_applied_in_backend(self):
        pop = self.genre("pop", "Pop")
        jazz = self.genre("jazz", "Jazz")
        relaxed = self.tag(category_code="MOOD", category_name="Mood", slug="relajado", name="Relajado")
        energetic = self.tag(category_code="ENERGY", category_name="Energy", slug="energetico", name="Energetico")
        self.song(title="Beta relaxed", internal_code="beta", genre=pop, tags=[relaxed], duration_ms=2000)
        self.song(title="Alpha energetic", internal_code="alpha", genre=pop, tags=[energetic], duration_ms=1000)
        self.song(title="Jazz relaxed", internal_code="jazz-relaxed", genre=jazz, tags=[relaxed], duration_ms=3000)
        self.authenticate()

        response = self.client.get(
            reverse("catalog-song-list"),
            {
                "search": "relaxed",
                "genre": "pop",
                "tags": "relajado",
                "ordering": "-duration_ms",
                "page": 1,
                "page_size": 1,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["page"], 1)
        self.assertEqual(response.data["page_size"], 1)
        self.assertEqual(response.data["results"][0]["title"], "Beta relaxed")

    def test_invalid_status_and_ordering_return_validation_errors(self):
        self.authenticate()

        status_response = self.client.get(reverse("catalog-song-list"), {"status": "UNKNOWN"})
        ordering_response = self.client.get(reverse("catalog-song-list"), {"ordering": "artist"})

        self.assertEqual(status_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("status", status_response.data["error"]["fields"])
        self.assertEqual(ordering_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("ordering", ordering_response.data["error"]["fields"])

    def test_metadata_absent_is_returned_as_null_or_empty_without_artist_or_album(self):
        song = self.song(title="No metadata", internal_code="no-metadata", duration_ms=None, tags=[])
        self.authenticate()

        response = self.client.get(reverse("catalog-song-detail", kwargs={"song_id": song.id}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data["duration_ms"])
        self.assertEqual(response.data["duration_unit"], "milliseconds")
        self.assertEqual(response.data["tags"], [])
        self.assertEqual(response.data["assets"], [])
        self.assertNotIn("artist", response.data)
        self.assertNotIn("album", response.data)

    def test_detail_exposes_only_ready_preview_asset_metadata_without_storage_keys(self):
        song = self.song(title="With assets", internal_code="with-assets")
        self.add_asset(song, role=AudioAsset.AssetRole.PREVIEW, processing_status=AudioAsset.ProcessingStatus.READY)
        self.add_asset(song, role=AudioAsset.AssetRole.STREAM, processing_status=AudioAsset.ProcessingStatus.READY)
        self.add_asset(song, role=AudioAsset.AssetRole.PREVIEW, processing_status=AudioAsset.ProcessingStatus.ERROR, version=2)
        self.authenticate()

        response = self.client.get(reverse("catalog-song-detail", kwargs={"song_id": song.id}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["assets"]), 1)
        asset = response.data["assets"][0]
        self.assertEqual(asset["asset_role"], "PREVIEW")
        self.assertEqual(asset["processing_status"], "READY")
        self.assertNotIn("storage_key", asset)
        self.assertNotIn("storage_backend", asset)
        self.assertNotIn("checksum_sha256", asset)

    def test_genres_and_tags_are_limited_to_accessible_songs(self):
        visible_genre = self.genre("ambient", "Ambient")
        hidden_genre = self.genre("punk", "Punk")
        visible_tag = self.tag(category_code="MOOD", category_name="Mood", slug="calm", name="Calm")
        hidden_tag = self.tag(category_code="STYLE", category_name="Style", slug="hidden", name="Hidden")
        other_company = f.company("catalog-filter-hidden")
        self.song(title="Visible", internal_code="visible-filter", genre=visible_genre, tags=[visible_tag])
        self.song(
            title="Hidden",
            internal_code="hidden-filter",
            company=other_company,
            visibility=AudioContent.Visibility.PRIVATE,
            genre=hidden_genre,
            tags=[hidden_tag],
        )
        self.authenticate()

        genres_response = self.client.get(reverse("catalog-genre-list"))
        tags_response = self.client.get(reverse("catalog-tag-list"), {"category": "MOOD"})

        self.assertEqual(genres_response.status_code, status.HTTP_200_OK)
        self.assertEqual([item["slug"] for item in genres_response.data["results"]], ["ambient"])
        self.assertEqual(tags_response.status_code, status.HTTP_200_OK)
        self.assertEqual([item["slug"] for item in tags_response.data["results"]], ["calm"])

    def test_expired_trial_blocks_catalog_product_access(self):
        subscription = self.company.subscriptions.get()
        subscription.trial_ends_at = timezone.now() - timedelta(days=1)
        subscription.current_period_end = subscription.trial_ends_at
        subscription.save(update_fields=["trial_ends_at", "current_period_end"])
        self.authenticate()

        response = self.client.get(reverse("catalog-song-list"))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["error"]["code"], "functional_access_blocked")
        self.assertEqual(response.data["error"]["block_reason"], "trial_expired")
