from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authorization.services import require_company_permission
from apps.catalog.exceptions import CatalogSongNotFound
from apps.catalog.models import AudioContent
from apps.catalog.selectors import (
    SONG_ORDERING_FIELDS,
    get_accessible_song_by_id,
    list_accessible_songs,
    list_available_genres_for_company,
    list_available_tags_for_company,
)
from apps.catalog.serializers import GenreSerializer, SongDetailSerializer, SongListSerializer, TagSerializer


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


class GenreListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        membership = require_company_permission(user=request.user, permission_code="catalog.view")
        genres = list_available_genres_for_company(company=membership.company)
        return Response({"results": GenreSerializer(genres, many=True).data})


class TagListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        membership = require_company_permission(user=request.user, permission_code="catalog.view")
        tags = list_available_tags_for_company(
            company=membership.company,
            category=request.query_params.get("category", "").strip(),
            search=request.query_params.get("search", "").strip(),
        )
        return Response({"results": TagSerializer(tags, many=True).data})


class SongListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        membership = require_company_permission(user=request.user, permission_code="catalog.view")
        status_value = request.query_params.get("status", "").strip().upper()
        ordering = request.query_params.get("ordering", "title").strip()
        if status_value and status_value not in AudioContent.Status.values:
            raise ValidationError({"status": ["Estado de contenido no valido."]})
        if ordering and ordering not in SONG_ORDERING_FIELDS:
            raise ValidationError({"ordering": ["Ordenacion no valida."]})
        queryset = list_accessible_songs(
            company=membership.company,
            search=request.query_params.get("search", ""),
            genre=request.query_params.get("genre", ""),
            tags=request.query_params.get("tags", ""),
            status_value=status_value,
            ordering=ordering,
        )
        return _paginated_response(
            queryset=queryset,
            serializer_class=SongListSerializer,
            request=request,
            context={"membership": membership},
        )


class SongDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, song_id):
        membership = require_company_permission(user=request.user, permission_code="catalog.view")
        song = get_accessible_song_by_id(company=membership.company, song_id=song_id)
        if not song:
            raise CatalogSongNotFound()
        return Response(SongDetailSerializer(song, context={"membership": membership}).data, status=status.HTTP_200_OK)
