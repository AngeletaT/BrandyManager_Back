from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authorization.services import (
    get_or_create_zone_scope,
    membership_has_permission_on_any_scope,
    require_company_permission,
)
from apps.billing.selectors import get_current_subscription_for_company
from apps.organizations.exceptions import ZoneNotFound
from apps.organizations.models import Zone
from apps.playlists.exceptions import ChannelNotFound, PlaylistItemNotFound, PlaylistNotFound
from apps.playlists.models import Channel, Playlist
from apps.playlists.selectors import (
    CHANNEL_ORDERING_FIELDS,
    PLAYLIST_ORDERING_FIELDS,
    get_accessible_channel_by_id,
    get_accessible_playlist_by_id,
    get_active_zone_channel_assignment,
    get_latest_published_snapshot,
    get_latest_published_channel_snapshot,
    get_owned_channel_by_id,
    get_owned_playlist_by_id,
    get_playlist_item,
    list_accessible_channels,
    list_channel_zone_assignments_for_membership,
    list_accessible_playlists,
)
from apps.playlists.serializers import (
    AssignChannelToZoneSerializer,
    ChannelCreateSerializer,
    ChannelDetailSerializer,
    ChannelDuplicateSerializer,
    ChannelExpectedRevisionSerializer,
    ChannelListSerializer,
    ChannelPolicyUpdateSerializer,
    ChannelReplacePlaylistsSerializer,
    ChannelSnapshotDetailSerializer,
    ChannelSnapshotSummarySerializer,
    ChannelUpdateSerializer,
    ChannelZoneAssignmentSerializer,
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
    UnassignChannelFromZoneSerializer,
)
from apps.playlists.services import (
    add_playlist_item,
    archive_playlist,
    archive_channel,
    assign_channel_to_zone,
    create_channel,
    create_playlist,
    duplicate_channel,
    duplicate_playlist,
    publish_channel,
    publish_playlist,
    reactivate_channel,
    reactivate_playlist,
    remove_playlist_item,
    reorder_playlist_items,
    replace_channel_playlists,
    replace_playlist_items,
    unassign_channel_from_zone,
    update_channel_metadata,
    update_channel_policy,
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


def _get_owned_channel_or_raise(*, membership, channel_id):
    channel = get_owned_channel_by_id(company=membership.company, channel_id=channel_id)
    if not channel:
        raise ChannelNotFound()
    return channel


def _get_channel_or_raise(*, membership, channel_id, permission_code="channels.view"):
    channel = get_accessible_channel_by_id(membership=membership, channel_id=channel_id, permission_code=permission_code)
    if not channel:
        raise ChannelNotFound()
    return channel


def _get_zone_for_permission_or_raise(*, request, zone_id, permission_code):
    membership = require_company_permission(
        user=request.user,
        permission_code=permission_code,
        check_functional_access=True,
    )
    zone = Zone.objects.select_related("site", "company").filter(company=membership.company, id=zone_id).first()
    if not zone:
        raise ZoneNotFound()
    zone_scope = get_or_create_zone_scope(zone=zone)
    require_company_permission(
        user=request.user,
        permission_code=permission_code,
        scope=zone_scope,
        check_functional_access=True,
    )
    return membership, zone


class ChannelListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        membership = require_company_permission(user=request.user, permission_code="channels.view")
        status_value = request.query_params.get("status", "").strip().upper()
        visibility = request.query_params.get("visibility", "").strip().upper()
        ordering = request.query_params.get("ordering", "name").strip()
        if status_value and status_value not in Channel.Status.values:
            raise ValidationError({"status": ["Estado de canal no valido."]})
        if visibility and visibility not in Channel.Visibility.values:
            raise ValidationError({"visibility": ["Visibilidad de canal no valida."]})
        if ordering and ordering not in CHANNEL_ORDERING_FIELDS:
            raise ValidationError({"ordering": ["Ordenacion no valida."]})
        queryset = list_accessible_channels(
            membership=membership,
            search=request.query_params.get("search", ""),
            status_value=status_value,
            visibility=visibility,
            ordering=ordering,
        )
        response = _paginated_response(
            queryset=queryset,
            serializer_class=ChannelListSerializer,
            request=request,
            context={"membership": membership},
        )
        subscription = get_current_subscription_for_company(company=membership.company)
        limits = subscription.effective_limits() if subscription else {}
        response.data["permissions"] = {
            "can_create": membership_has_permission_on_any_scope(
                membership=membership,
                permission_code="channels.manage",
            )
        }
        response.data["usage"] = {
            "used": Channel.objects.filter(owner_company=membership.company)
            .exclude(status=Channel.Status.ARCHIVED)
            .count(),
            "limit": limits.get("channels"),
        }
        return response

    def post(self, request):
        membership = require_company_permission(user=request.user, permission_code="channels.manage")
        serializer = ChannelCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        channel = create_channel(company=membership.company, data=serializer.validated_data, actor=request.user)
        return Response(ChannelDetailSerializer(channel, context={"membership": membership}).data, status=status.HTTP_201_CREATED)


class ChannelDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, channel_id):
        membership = require_company_permission(user=request.user, permission_code="channels.view")
        channel = _get_channel_or_raise(membership=membership, channel_id=channel_id)
        return Response(ChannelDetailSerializer(channel, context={"membership": membership}).data)

    def patch(self, request, channel_id):
        membership = require_company_permission(user=request.user, permission_code="channels.manage")
        channel = _get_owned_channel_or_raise(membership=membership, channel_id=channel_id)
        if channel.status == Channel.Status.ARCHIVED:
            raise ChannelNotFound()
        serializer = ChannelUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        channel = update_channel_metadata(channel=channel, data=dict(serializer.validated_data))
        return Response(ChannelDetailSerializer(channel, context={"membership": membership}).data)


class ChannelPolicyView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, channel_id):
        membership = require_company_permission(user=request.user, permission_code="channels.manage")
        channel = _get_owned_channel_or_raise(membership=membership, channel_id=channel_id)
        if channel.status == Channel.Status.ARCHIVED:
            raise ChannelNotFound()
        serializer = ChannelPolicyUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        channel = update_channel_policy(channel=channel, data=dict(serializer.validated_data))
        return Response(ChannelDetailSerializer(channel, context={"membership": membership}).data)


class ChannelPlaylistConfigView(APIView):
    permission_classes = [IsAuthenticated]

    def put(self, request, channel_id):
        membership = require_company_permission(user=request.user, permission_code="channels.manage")
        channel = _get_owned_channel_or_raise(membership=membership, channel_id=channel_id)
        if channel.status == Channel.Status.ARCHIVED:
            raise ChannelNotFound()
        serializer = ChannelReplacePlaylistsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        channel = replace_channel_playlists(
            company=membership.company,
            channel=channel,
            playlists=serializer.validated_data["playlists"],
            expected_revision=serializer.validated_data["expected_revision"],
        )
        return Response(ChannelDetailSerializer(channel, context={"membership": membership}).data)


class ChannelDuplicateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, channel_id):
        membership = require_company_permission(user=request.user, permission_code="channels.manage")
        channel = _get_channel_or_raise(membership=membership, channel_id=channel_id)
        serializer = ChannelDuplicateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        copy = duplicate_channel(
            company=membership.company,
            channel=channel,
            actor=request.user,
            name=serializer.validated_data.get("name", ""),
            code=serializer.validated_data.get("code", ""),
        )
        return Response(ChannelDetailSerializer(copy, context={"membership": membership}).data, status=status.HTTP_201_CREATED)


class ChannelPublishView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, channel_id):
        membership = require_company_permission(user=request.user, permission_code="channels.manage")
        channel = _get_owned_channel_or_raise(membership=membership, channel_id=channel_id)
        serializer = ChannelExpectedRevisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        snapshot = publish_channel(
            channel=channel,
            company=membership.company,
            published_by=request.user,
            expected_revision=serializer.validated_data["expected_revision"],
        )
        channel.refresh_from_db()
        return Response(
            {
                "channel": {
                    "id": str(channel.id),
                    "status": channel.status,
                    "current_version": channel.current_version,
                    "revision": channel.revision,
                    "published_at": channel.published_at,
                },
                "snapshot": ChannelSnapshotSummarySerializer(snapshot).data,
            },
            status=status.HTTP_201_CREATED,
        )


class ChannelPublishedConfigurationView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, channel_id):
        membership = require_company_permission(user=request.user, permission_code="channels.view")
        channel = _get_channel_or_raise(membership=membership, channel_id=channel_id)
        snapshot = get_latest_published_channel_snapshot(channel=channel)
        return Response(
            {
                "channel": {
                    "id": str(channel.id),
                    "status": channel.status,
                    "current_version": channel.current_version,
                    "revision": channel.revision,
                },
                "snapshot": ChannelSnapshotDetailSerializer(snapshot).data if snapshot else None,
            }
        )


class ChannelZonesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, channel_id):
        membership = require_company_permission(user=request.user, permission_code="channels.view")
        channel = _get_channel_or_raise(membership=membership, channel_id=channel_id)
        assignments = list_channel_zone_assignments_for_membership(channel=channel, membership=membership)
        return Response({"results": ChannelZoneAssignmentSerializer(assignments, many=True).data})


class ChannelArchiveView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, channel_id):
        membership = require_company_permission(user=request.user, permission_code="channels.manage")
        channel = _get_owned_channel_or_raise(membership=membership, channel_id=channel_id)
        serializer = ChannelExpectedRevisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        channel = archive_channel(channel=channel, expected_revision=serializer.validated_data["expected_revision"])
        return Response(ChannelDetailSerializer(channel, context={"membership": membership}).data)


class ChannelReactivateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, channel_id):
        membership = require_company_permission(user=request.user, permission_code="channels.manage")
        channel = _get_owned_channel_or_raise(membership=membership, channel_id=channel_id)
        serializer = ChannelExpectedRevisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        channel = reactivate_channel(
            company=membership.company,
            channel=channel,
            expected_revision=serializer.validated_data["expected_revision"],
        )
        return Response(ChannelDetailSerializer(channel, context={"membership": membership}).data)


class ZoneChannelAssignmentView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, zone_id):
        membership, zone = _get_zone_for_permission_or_raise(request=request, zone_id=zone_id, permission_code="channels.view")
        assignment = get_active_zone_channel_assignment(zone=zone)
        return Response({"assignment": ChannelZoneAssignmentSerializer(assignment).data if assignment else None})

    def put(self, request, zone_id):
        membership, zone = _get_zone_for_permission_or_raise(request=request, zone_id=zone_id, permission_code="channels.select")
        serializer = AssignChannelToZoneSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        channel = get_owned_channel_by_id(company=membership.company, channel_id=serializer.validated_data["channel_id"])
        if not channel:
            raise ChannelNotFound()
        assignment = assign_channel_to_zone(
            company=membership.company,
            zone=zone,
            channel=channel,
            actor=request.user,
            reason=serializer.validated_data.get("reason", ""),
        )
        return Response(ChannelZoneAssignmentSerializer(assignment).data)

    def delete(self, request, zone_id):
        membership, zone = _get_zone_for_permission_or_raise(request=request, zone_id=zone_id, permission_code="channels.select")
        serializer = UnassignChannelFromZoneSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        assignment = unassign_channel_from_zone(
            company=membership.company,
            zone=zone,
            actor=request.user,
            reason=serializer.validated_data.get("reason", ""),
        )
        return Response({"assignment": ChannelZoneAssignmentSerializer(assignment).data if assignment else None})
