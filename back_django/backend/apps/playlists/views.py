from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authorization.services import require_company_permission
from apps.playlists.exceptions import PlaylistItemNotFound, PlaylistNotFound
from apps.playlists.models import Playlist
from apps.playlists.selectors import (
    PLAYLIST_ORDERING_FIELDS,
    get_accessible_playlist_by_id,
    get_latest_published_snapshot,
    get_owned_playlist_by_id,
    get_playlist_item,
    list_accessible_playlists,
)
from apps.playlists.serializers import (
    PlaylistAddItemSerializer,
    PlaylistCreateSerializer,
    PlaylistDetailSerializer,
    PlaylistDuplicateSerializer,
    PlaylistExpectedRevisionSerializer,
    PlaylistListSerializer,
    PlaylistReorderItemsSerializer,
    PlaylistReplaceItemsSerializer,
    PlaylistSnapshotSummarySerializer,
    PlaylistUpdateSerializer,
)
from apps.playlists.services import (
    add_playlist_item,
    archive_playlist,
    create_playlist,
    duplicate_playlist,
    publish_playlist,
    reactivate_playlist,
    remove_playlist_item,
    reorder_playlist_items,
    replace_playlist_items,
    update_playlist_metadata,
)


def _parse_positive_int(value, default, *, field, maximum=None):
    try:
        parsed = int(value or default)
    except (TypeError, ValueError) as exc:
        raise ValidationError({field: ["Debe ser un numero entero positivo."]}) from exc
    if parsed < 1:
        raise ValidationError({field: ["Debe ser un numero entero positivo."]})
    if maximum:
        return min(parsed, maximum)
    return parsed


def _paginated_response(*, queryset, serializer_class, request, context=None):
    page = _parse_positive_int(request.query_params.get("page"), 1, field="page")
    page_size = _parse_positive_int(request.query_params.get("page_size"), 20, field="page_size", maximum=100)
    count = queryset.count()
    start = (page - 1) * page_size
    end = start + page_size
    serializer = serializer_class(queryset[start:end], many=True, context=context or {})
    return Response(
        {
            "count": count,
            "page": page,
            "page_size": page_size,
            "results": serializer.data,
        }
    )


class PlaylistListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        membership = require_company_permission(user=request.user, permission_code="playlists.view")
        status_value = request.query_params.get("status", "").strip().upper()
        visibility = request.query_params.get("visibility", "").strip().upper()
        ordering = request.query_params.get("ordering", "name").strip()
        if status_value and status_value not in Playlist.Status.values:
            raise ValidationError({"status": ["Estado de playlist no valido."]})
        if visibility and visibility not in Playlist.Visibility.values:
            raise ValidationError({"visibility": ["Visibilidad de playlist no valida."]})
        if ordering and ordering not in PLAYLIST_ORDERING_FIELDS:
            raise ValidationError({"ordering": ["Ordenacion no valida."]})
        queryset = list_accessible_playlists(
            company=membership.company,
            search=request.query_params.get("search", ""),
            status_value=status_value,
            visibility=visibility,
            ordering=ordering,
        )
        return _paginated_response(
            queryset=queryset,
            serializer_class=PlaylistListSerializer,
            request=request,
            context={"membership": membership},
        )

    def post(self, request):
        membership = require_company_permission(user=request.user, permission_code="playlists.manage")
        serializer = PlaylistCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        playlist = create_playlist(company=membership.company, data=serializer.validated_data, actor=request.user)
        return Response(
            PlaylistDetailSerializer(playlist, context={"membership": membership}).data,
            status=status.HTTP_201_CREATED,
        )


class PlaylistDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, playlist_id):
        membership = require_company_permission(user=request.user, permission_code="playlists.view")
        playlist = get_accessible_playlist_by_id(company=membership.company, playlist_id=playlist_id)
        if not playlist:
            raise PlaylistNotFound()
        return Response(PlaylistDetailSerializer(playlist, context={"membership": membership}).data)

    def patch(self, request, playlist_id):
        membership = require_company_permission(user=request.user, permission_code="playlists.manage")
        playlist = get_owned_playlist_by_id(company=membership.company, playlist_id=playlist_id)
        if not playlist:
            raise PlaylistNotFound()
        if playlist.status == Playlist.Status.ARCHIVED:
            raise PlaylistNotFound()
        serializer = PlaylistUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        playlist = update_playlist_metadata(playlist=playlist, data=dict(serializer.validated_data))
        return Response(PlaylistDetailSerializer(playlist, context={"membership": membership}).data)


class PlaylistItemListView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, playlist_id):
        membership = require_company_permission(user=request.user, permission_code="playlists.manage")
        playlist = get_owned_playlist_by_id(company=membership.company, playlist_id=playlist_id)
        if not playlist or playlist.status == Playlist.Status.ARCHIVED:
            raise PlaylistNotFound()
        serializer = PlaylistAddItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        playlist = add_playlist_item(
            company=membership.company,
            playlist=playlist,
            song_id=serializer.validated_data["song_id"],
            weight=serializer.validated_data["weight"],
            expected_revision=serializer.validated_data["expected_revision"],
            actor=request.user,
        )
        return Response(PlaylistDetailSerializer(playlist, context={"membership": membership}).data, status=status.HTTP_201_CREATED)

    def put(self, request, playlist_id):
        membership = require_company_permission(user=request.user, permission_code="playlists.manage")
        playlist = get_owned_playlist_by_id(company=membership.company, playlist_id=playlist_id)
        if not playlist or playlist.status == Playlist.Status.ARCHIVED:
            raise PlaylistNotFound()
        serializer = PlaylistReplaceItemsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        playlist = replace_playlist_items(
            company=membership.company,
            playlist=playlist,
            items=serializer.validated_data["items"],
            expected_revision=serializer.validated_data["expected_revision"],
            actor=request.user,
        )
        return Response(PlaylistDetailSerializer(playlist, context={"membership": membership}).data)


class PlaylistItemDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, playlist_id, item_id):
        membership = require_company_permission(user=request.user, permission_code="playlists.manage")
        playlist = get_owned_playlist_by_id(company=membership.company, playlist_id=playlist_id)
        if not playlist or playlist.status == Playlist.Status.ARCHIVED:
            raise PlaylistNotFound()
        item = get_playlist_item(playlist=playlist, item_id=item_id)
        if not item:
            raise PlaylistItemNotFound()
        serializer = PlaylistExpectedRevisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        playlist = remove_playlist_item(
            playlist=playlist,
            item=item,
            expected_revision=serializer.validated_data["expected_revision"],
        )
        return Response(PlaylistDetailSerializer(playlist, context={"membership": membership}).data)


class PlaylistItemOrderView(APIView):
    permission_classes = [IsAuthenticated]

    def put(self, request, playlist_id):
        membership = require_company_permission(user=request.user, permission_code="playlists.manage")
        playlist = get_owned_playlist_by_id(company=membership.company, playlist_id=playlist_id)
        if not playlist or playlist.status == Playlist.Status.ARCHIVED:
            raise PlaylistNotFound()
        serializer = PlaylistReorderItemsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        playlist = reorder_playlist_items(
            playlist=playlist,
            item_ids=serializer.validated_data["item_ids"],
            expected_revision=serializer.validated_data["expected_revision"],
        )
        return Response(PlaylistDetailSerializer(playlist, context={"membership": membership}).data)


class PlaylistDuplicateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, playlist_id):
        membership = require_company_permission(user=request.user, permission_code="playlists.manage")
        playlist = get_accessible_playlist_by_id(company=membership.company, playlist_id=playlist_id)
        if not playlist:
            raise PlaylistNotFound()
        serializer = PlaylistDuplicateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        copy = duplicate_playlist(
            company=membership.company,
            playlist=playlist,
            actor=request.user,
            name=serializer.validated_data.get("name", ""),
            code=serializer.validated_data.get("code", ""),
        )
        return Response(PlaylistDetailSerializer(copy, context={"membership": membership}).data, status=status.HTTP_201_CREATED)


class PlaylistPublishView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, playlist_id):
        membership = require_company_permission(user=request.user, permission_code="playlists.manage")
        playlist = get_owned_playlist_by_id(company=membership.company, playlist_id=playlist_id)
        if not playlist or playlist.status == Playlist.Status.ARCHIVED:
            raise PlaylistNotFound()
        serializer = PlaylistExpectedRevisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        snapshot = publish_playlist(
            playlist=playlist,
            company=membership.company,
            published_by=request.user,
            expected_revision=serializer.validated_data["expected_revision"],
        )
        playlist.refresh_from_db()
        return Response(
            {
                "playlist": {
                    "id": str(playlist.id),
                    "status": playlist.status,
                    "current_version": playlist.current_version,
                    "revision": playlist.revision,
                    "published_at": playlist.published_at,
                },
                "snapshot": PlaylistSnapshotSummarySerializer(snapshot).data,
            },
            status=status.HTTP_201_CREATED,
        )


class PlaylistPublishedVersionView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, playlist_id):
        membership = require_company_permission(user=request.user, permission_code="playlists.view")
        playlist = get_accessible_playlist_by_id(company=membership.company, playlist_id=playlist_id)
        if not playlist:
            raise PlaylistNotFound()
        snapshot = get_latest_published_snapshot(playlist=playlist)
        return Response({"snapshot": PlaylistSnapshotSummarySerializer(snapshot).data if snapshot else None})


class PlaylistArchiveView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, playlist_id):
        membership = require_company_permission(user=request.user, permission_code="playlists.manage")
        playlist = get_owned_playlist_by_id(company=membership.company, playlist_id=playlist_id)
        if not playlist:
            raise PlaylistNotFound()
        serializer = PlaylistExpectedRevisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        playlist = archive_playlist(playlist=playlist, expected_revision=serializer.validated_data["expected_revision"])
        return Response(PlaylistDetailSerializer(playlist, context={"membership": membership}).data)


class PlaylistReactivateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, playlist_id):
        membership = require_company_permission(user=request.user, permission_code="playlists.manage")
        playlist = get_owned_playlist_by_id(company=membership.company, playlist_id=playlist_id)
        if not playlist:
            raise PlaylistNotFound()
        serializer = PlaylistExpectedRevisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        playlist = reactivate_playlist(
            company=membership.company,
            playlist=playlist,
            expected_revision=serializer.validated_data["expected_revision"],
        )
        return Response(PlaylistDetailSerializer(playlist, context={"membership": membership}).data)
