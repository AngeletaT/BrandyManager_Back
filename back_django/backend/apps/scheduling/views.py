from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authorization.services import require_company_permission
from apps.organizations.exceptions import ZoneNotFound
from apps.organizations.selectors import get_zone_for_membership
from apps.organizations.models import ResourceScope
from apps.scheduling.exceptions import (
    ScheduleAssignmentNotFound,
    ScheduleBlockNotFound,
    ScheduleExceptionNotFound,
    ScheduleNotFound,
)
from apps.scheduling.models import Schedule
from apps.scheduling.selectors import (
    SCHEDULE_ORDERING_FIELDS,
    get_schedule_assignment,
    get_schedule_block,
    get_schedule_exception,
    get_schedule_for_membership,
    list_schedules_for_membership,
    resolve_effective_schedule_for_zone,
)
from apps.scheduling.serializers import (
    ScheduleAssignmentSerializer,
    ScheduleAssignmentUpdateSerializer,
    ScheduleAssignmentWriteSerializer,
    ScheduleBlockSerializer,
    ScheduleBlockUpdateSerializer,
    ScheduleBlockWriteSerializer,
    ScheduleDetailSerializer,
    ScheduleExceptionSerializer,
    ScheduleExceptionUpdateSerializer,
    ScheduleExceptionWriteSerializer,
    ScheduleExpectedRevisionSerializer,
    ScheduleListSerializer,
    ScheduleOccurrenceQuerySerializer,
    ScheduleResolveQuerySerializer,
    ScheduleUpdateSerializer,
    ScheduleWriteSerializer,
    schedule_occurrences_response,
)
from apps.scheduling.services import (
    archive_schedule,
    create_schedule,
    create_schedule_assignment,
    create_schedule_block,
    create_schedule_exception,
    deactivate_schedule_assignment,
    delete_schedule_block,
    delete_schedule_exception,
    disable_schedule,
    publish_schedule,
    reactivate_schedule,
    update_schedule_assignment,
    update_schedule_block,
    update_schedule_exception,
    update_schedule_metadata,
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
    return Response({"count": count, "page": page, "page_size": page_size, "results": serializer.data})


def _get_schedule_or_raise(*, request, schedule_id, permission_code, check_functional_access=False):
    membership = require_company_permission(
        user=request.user,
        permission_code=permission_code,
        check_functional_access=check_functional_access,
    )
    schedule = get_schedule_for_membership(membership=membership, schedule_id=schedule_id, permission_code=permission_code)
    if not schedule:
        raise ScheduleNotFound()
    return membership, schedule


class ScheduleListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        membership = require_company_permission(
            user=request.user,
            permission_code="schedules.view",
            check_functional_access=False,
        )
        status_value = request.query_params.get("status", "").strip().upper()
        scope_type = request.query_params.get("scope_type", "").strip().upper()
        ordering = request.query_params.get("ordering", "name").strip()
        if status_value and status_value not in Schedule.Status.values:
            raise ValidationError({"status": ["Estado de programacion no valido."]})
        if scope_type and scope_type not in [
            ResourceScope.ScopeType.COMPANY,
            ResourceScope.ScopeType.SITE,
            ResourceScope.ScopeType.ZONE,
        ]:
            raise ValidationError({"scope_type": ["Scope no admitido en Fase 3."]})
        if ordering not in SCHEDULE_ORDERING_FIELDS:
            raise ValidationError({"ordering": ["Ordenacion no valida."]})
        queryset = list_schedules_for_membership(
            membership=membership,
            search=request.query_params.get("search", ""),
            status_value=status_value,
            scope_type=scope_type,
            site_id=request.query_params.get("site_id"),
            zone_id=request.query_params.get("zone_id"),
            ordering=ordering,
        )
        return _paginated_response(
            queryset=queryset,
            serializer_class=ScheduleListSerializer,
            request=request,
            context={"membership": membership},
        )

    def post(self, request):
        membership = require_company_permission(user=request.user, permission_code="schedules.manage")
        serializer = ScheduleWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        schedule = create_schedule(company=membership.company, data=serializer.validated_data, actor=request.user)
        return Response(ScheduleDetailSerializer(schedule, context={"membership": membership}).data, status=status.HTTP_201_CREATED)


class ScheduleDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, schedule_id):
        membership, schedule = _get_schedule_or_raise(request=request, schedule_id=schedule_id, permission_code="schedules.view")
        return Response(ScheduleDetailSerializer(schedule, context={"membership": membership}).data)

    def patch(self, request, schedule_id):
        membership, schedule = _get_schedule_or_raise(
            request=request,
            schedule_id=schedule_id,
            permission_code="schedules.manage",
            check_functional_access=True,
        )
        if schedule.status == Schedule.Status.ARCHIVED:
            raise ScheduleNotFound()
        serializer = ScheduleUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        schedule = update_schedule_metadata(schedule=schedule, data=dict(serializer.validated_data))
        return Response(ScheduleDetailSerializer(schedule, context={"membership": membership}).data)


class ScheduleBlockListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, schedule_id):
        membership, schedule = _get_schedule_or_raise(request=request, schedule_id=schedule_id, permission_code="schedules.view")
        return Response({"results": ScheduleBlockSerializer(schedule.blocks.select_related("playlist").order_by("day_of_week", "start_time"), many=True).data})

    def post(self, request, schedule_id):
        membership, schedule = _get_schedule_or_raise(
            request=request,
            schedule_id=schedule_id,
            permission_code="schedules.manage",
            check_functional_access=True,
        )
        serializer = ScheduleBlockWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        schedule = create_schedule_block(company=membership.company, schedule=schedule, data=dict(serializer.validated_data))
        return Response(ScheduleDetailSerializer(schedule, context={"membership": membership}).data, status=status.HTTP_201_CREATED)


class ScheduleBlockDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, schedule_id, block_id):
        membership, schedule = _get_schedule_or_raise(
            request=request,
            schedule_id=schedule_id,
            permission_code="schedules.manage",
            check_functional_access=True,
        )
        block = get_schedule_block(schedule=schedule, block_id=block_id)
        if not block:
            raise ScheduleBlockNotFound()
        serializer = ScheduleBlockUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        schedule = update_schedule_block(company=membership.company, schedule=schedule, block=block, data=dict(serializer.validated_data))
        return Response(ScheduleDetailSerializer(schedule, context={"membership": membership}).data)

    def delete(self, request, schedule_id, block_id):
        membership, schedule = _get_schedule_or_raise(
            request=request,
            schedule_id=schedule_id,
            permission_code="schedules.manage",
            check_functional_access=True,
        )
        block = get_schedule_block(schedule=schedule, block_id=block_id)
        if not block:
            raise ScheduleBlockNotFound()
        serializer = ScheduleExpectedRevisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        delete_schedule_block(schedule=schedule, block=block, expected_revision=serializer.validated_data["expected_revision"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class ScheduleExceptionListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, schedule_id):
        membership, schedule = _get_schedule_or_raise(request=request, schedule_id=schedule_id, permission_code="schedules.view")
        return Response({"results": ScheduleExceptionSerializer(schedule.exceptions.select_related("playlist").order_by("date", "start_time"), many=True).data})

    def post(self, request, schedule_id):
        membership, schedule = _get_schedule_or_raise(
            request=request,
            schedule_id=schedule_id,
            permission_code="schedules.manage",
            check_functional_access=True,
        )
        serializer = ScheduleExceptionWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        schedule = create_schedule_exception(company=membership.company, schedule=schedule, data=dict(serializer.validated_data))
        return Response(ScheduleDetailSerializer(schedule, context={"membership": membership}).data, status=status.HTTP_201_CREATED)


class ScheduleExceptionDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, schedule_id, exception_id):
        membership, schedule = _get_schedule_or_raise(
            request=request,
            schedule_id=schedule_id,
            permission_code="schedules.manage",
            check_functional_access=True,
        )
        exception = get_schedule_exception(schedule=schedule, exception_id=exception_id)
        if not exception:
            raise ScheduleExceptionNotFound()
        serializer = ScheduleExceptionUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        schedule = update_schedule_exception(company=membership.company, schedule=schedule, exception=exception, data=dict(serializer.validated_data))
        return Response(ScheduleDetailSerializer(schedule, context={"membership": membership}).data)

    def delete(self, request, schedule_id, exception_id):
        membership, schedule = _get_schedule_or_raise(
            request=request,
            schedule_id=schedule_id,
            permission_code="schedules.manage",
            check_functional_access=True,
        )
        exception = get_schedule_exception(schedule=schedule, exception_id=exception_id)
        if not exception:
            raise ScheduleExceptionNotFound()
        serializer = ScheduleExpectedRevisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        delete_schedule_exception(schedule=schedule, exception=exception, expected_revision=serializer.validated_data["expected_revision"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class ScheduleAssignmentListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, schedule_id):
        membership, schedule = _get_schedule_or_raise(request=request, schedule_id=schedule_id, permission_code="schedules.view")
        assignments = schedule.assignments.select_related("scope", "scope__site", "scope__zone").order_by("-is_active", "-priority")
        return Response({"results": ScheduleAssignmentSerializer(assignments, many=True).data})

    def post(self, request, schedule_id):
        membership, schedule = _get_schedule_or_raise(
            request=request,
            schedule_id=schedule_id,
            permission_code="schedules.manage",
            check_functional_access=True,
        )
        serializer = ScheduleAssignmentWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        schedule = create_schedule_assignment(company=membership.company, schedule=schedule, data=dict(serializer.validated_data), actor=request.user)
        return Response(ScheduleDetailSerializer(schedule, context={"membership": membership}).data, status=status.HTTP_201_CREATED)


class ScheduleAssignmentDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, schedule_id, assignment_id):
        membership, schedule = _get_schedule_or_raise(
            request=request,
            schedule_id=schedule_id,
            permission_code="schedules.manage",
            check_functional_access=True,
        )
        assignment = get_schedule_assignment(schedule=schedule, assignment_id=assignment_id)
        if not assignment:
            raise ScheduleAssignmentNotFound()
        serializer = ScheduleAssignmentUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        schedule = update_schedule_assignment(schedule=schedule, assignment=assignment, data=dict(serializer.validated_data))
        return Response(ScheduleDetailSerializer(schedule, context={"membership": membership}).data)

    def delete(self, request, schedule_id, assignment_id):
        membership, schedule = _get_schedule_or_raise(
            request=request,
            schedule_id=schedule_id,
            permission_code="schedules.manage",
            check_functional_access=True,
        )
        assignment = get_schedule_assignment(schedule=schedule, assignment_id=assignment_id)
        if not assignment:
            raise ScheduleAssignmentNotFound()
        serializer = ScheduleExpectedRevisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        schedule = deactivate_schedule_assignment(schedule=schedule, assignment=assignment, expected_revision=serializer.validated_data["expected_revision"])
        return Response(ScheduleDetailSerializer(schedule, context={"membership": membership}).data)


class SchedulePublishView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, schedule_id):
        membership, schedule = _get_schedule_or_raise(
            request=request,
            schedule_id=schedule_id,
            permission_code="schedules.manage",
            check_functional_access=True,
        )
        serializer = ScheduleExpectedRevisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        schedule = publish_schedule(schedule=schedule, expected_revision=serializer.validated_data["expected_revision"])
        return Response(ScheduleDetailSerializer(schedule, context={"membership": membership}).data)


class ScheduleArchiveView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, schedule_id):
        membership, schedule = _get_schedule_or_raise(
            request=request,
            schedule_id=schedule_id,
            permission_code="schedules.manage",
            check_functional_access=True,
        )
        serializer = ScheduleExpectedRevisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        schedule = archive_schedule(schedule=schedule, expected_revision=serializer.validated_data["expected_revision"])
        return Response(ScheduleDetailSerializer(schedule, context={"membership": membership}).data)


class ScheduleReactivateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, schedule_id):
        membership, schedule = _get_schedule_or_raise(
            request=request,
            schedule_id=schedule_id,
            permission_code="schedules.manage",
            check_functional_access=True,
        )
        serializer = ScheduleExpectedRevisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        schedule = reactivate_schedule(schedule=schedule, expected_revision=serializer.validated_data["expected_revision"])
        return Response(ScheduleDetailSerializer(schedule, context={"membership": membership}).data)


class ScheduleDisableView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, schedule_id):
        membership, schedule = _get_schedule_or_raise(
            request=request,
            schedule_id=schedule_id,
            permission_code="schedules.manage",
            check_functional_access=True,
        )
        serializer = ScheduleExpectedRevisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        schedule = disable_schedule(schedule=schedule, expected_revision=serializer.validated_data["expected_revision"])
        return Response(ScheduleDetailSerializer(schedule, context={"membership": membership}).data)


class ScheduleOccurrencesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, schedule_id):
        membership, schedule = _get_schedule_or_raise(request=request, schedule_id=schedule_id, permission_code="schedules.view")
        serializer = ScheduleOccurrenceQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        return Response(
            schedule_occurrences_response(
                schedule=schedule,
                start_at=serializer.validated_data.get("start_at") or timezone.now(),
                days=serializer.validated_data["days"],
                limit=serializer.validated_data["limit"],
            )
        )


class ScheduleResolveView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        membership = require_company_permission(
            user=request.user,
            permission_code="schedules.view",
            check_functional_access=False,
        )
        serializer = ScheduleResolveQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        zone = get_zone_for_membership(membership=membership, zone_id=serializer.validated_data["zone_id"], permission_code="schedules.view")
        if not zone:
            raise ZoneNotFound()
        at = serializer.validated_data.get("at") or timezone.now()
        result = resolve_effective_schedule_for_zone(zone=zone, at=at)
        schedule = result["schedule"]
        block = result["block"]
        exception = result["exception"]
        assignment = result["assignment"]
        return Response(
            {
                "calculation_type": "configuration_preview",
                "execution_observed": False,
                "zone": {"id": str(zone.id), "name": zone.name},
                "at": at,
                "schedule": ScheduleListSerializer(schedule, context={"membership": membership}).data if schedule else None,
                "assignment": ScheduleAssignmentSerializer(assignment).data if assignment else None,
                "block": ScheduleBlockSerializer(block).data if block else None,
                "exception": ScheduleExceptionSerializer(exception).data if exception else None,
                "content": {
                    "content_type": result["content_kind"],
                    "playlist": ScheduleBlockSerializer(block).data["playlist"] if block and block.playlist_id else (
                        ScheduleExceptionSerializer(exception).data["playlist"] if exception and exception.playlist_id else None
                    ),
                },
            }
        )

