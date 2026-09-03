from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authorization.services import PermissionDenied, require_company_permission
from apps.organizations.exceptions import InvitationNotFound, MembershipNotFound, SiteNotFound, ZoneNotFound
from apps.organizations.selectors import (
    get_invitation_for_company,
    get_membership_for_company,
    get_site_for_membership,
    get_zone_for_membership,
    list_invitations_for_company,
    list_memberships_for_company,
    list_sites_for_membership,
    list_zones_for_membership,
)
from apps.organizations.serializers import (
    CompanyDetailSerializer,
    CompanyUpdateSerializer,
    InvitationAcceptSerializer,
    InvitationCreateSerializer,
    InvitationValidateSerializer,
    MembershipUpdateSerializer,
    SiteCreateSerializer,
    SiteSerializer,
    SiteUpdateSerializer,
    ZoneCreateSerializer,
    ZoneSerializer,
    ZoneUpdateSerializer,
    serialize_invitation,
    serialize_membership,
)
from apps.organizations.services import (
    accept_company_invitation,
    activate_site,
    activate_zone,
    archive_site,
    archive_zone,
    cancel_invitation,
    create_site,
    create_zone,
    get_invitation_scopes,
    invite_company_member,
    reactivate_member,
    resend_invitation,
    suspend_member,
    update_company_profile,
    update_member_role_and_scopes,
    update_site,
    update_zone,
    validate_company_invitation_token,
)


User = get_user_model()
SITE_OPERATIONAL_FIELDS = {"contact_name", "contact_email", "contact_phone"}
ZONE_OPERATIONAL_FIELDS = {"description", "timezone"}


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


class MyCompanyView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        membership = require_company_permission(
            user=request.user,
            permission_code="company.view",
            check_functional_access=False,
        )
        return Response(CompanyDetailSerializer(membership.company, context={"membership": membership}).data)

    def patch(self, request):
        membership = require_company_permission(user=request.user, permission_code="company.update")
        serializer = CompanyUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        company = update_company_profile(company=membership.company, data=serializer.validated_data, actor=request.user)
        return Response(CompanyDetailSerializer(company, context={"membership": membership}).data)


class SiteListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        membership = require_company_permission(user=request.user, permission_code="sites.view")
        status_value = request.query_params.get("status", "").strip().upper()
        site_type = request.query_params.get("site_type", "").strip().upper()
        if status_value and status_value not in SiteSerializer.Meta.model.Status.values:
            raise ValidationError({"status": ["Estado de sede no valido."]})
        if site_type and site_type not in SiteSerializer.Meta.model.SiteType.values:
            raise ValidationError({"site_type": ["Tipo de sede no valido."]})
        queryset = list_sites_for_membership(
            membership=membership,
            search=request.query_params.get("search", "").strip(),
            status_value=status_value,
            site_type=site_type,
        )
        return _paginated_response(
            queryset=queryset,
            serializer_class=SiteSerializer,
            request=request,
            context={"membership": membership},
        )

    def post(self, request):
        membership = require_company_permission(user=request.user, permission_code="sites.create")
        serializer = SiteCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        site = create_site(company=membership.company, data=serializer.validated_data, actor=request.user)
        return Response(SiteSerializer(site, context={"membership": membership}).data, status=status.HTTP_201_CREATED)


class SiteDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get_site(self, *, request, site_id, permission_code):
        membership = require_company_permission(user=request.user, permission_code=permission_code)
        site = get_site_for_membership(membership=membership, site_id=site_id, permission_code=permission_code)
        if not site:
            raise SiteNotFound()
        return membership, site

    def get(self, request, site_id):
        membership, site = self.get_site(request=request, site_id=site_id, permission_code="sites.view")
        return Response(SiteSerializer(site, context={"membership": membership}).data)

    def patch(self, request, site_id):
        permission_code = "sites.update"
        try:
            membership = require_company_permission(user=request.user, permission_code=permission_code)
        except PermissionDenied:
            if set(request.data.keys()) - SITE_OPERATIONAL_FIELDS:
                raise
            permission_code = "sites.update_operational"
            membership = require_company_permission(user=request.user, permission_code=permission_code)

        site = get_site_for_membership(membership=membership, site_id=site_id, permission_code=permission_code)
        if not site:
            raise SiteNotFound()
        if site.status == SiteSerializer.Meta.model.Status.ARCHIVED:
            raise PermissionDenied()
        serializer = SiteUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        site = update_site(site=site, data=serializer.validated_data)
        return Response(SiteSerializer(site, context={"membership": membership}).data)


class SiteArchiveView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, site_id):
        membership = require_company_permission(user=request.user, permission_code="sites.archive")
        site = get_site_for_membership(membership=membership, site_id=site_id, permission_code="sites.archive")
        if not site:
            raise SiteNotFound()
        return Response(SiteSerializer(archive_site(site=site), context={"membership": membership}).data)


class SiteReactivateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, site_id):
        membership = require_company_permission(user=request.user, permission_code="sites.update")
        site = get_site_for_membership(membership=membership, site_id=site_id, permission_code="sites.update")
        if not site:
            raise SiteNotFound()
        return Response(SiteSerializer(activate_site(site=site), context={"membership": membership}).data)


SiteActivateView = SiteReactivateView


class ZoneListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        membership = require_company_permission(user=request.user, permission_code="zones.view")
        status_value = request.query_params.get("status", "").strip().upper()
        if status_value and status_value not in ZoneSerializer.Meta.model.Status.values:
            raise ValidationError({"status": ["Estado de zona no valido."]})
        queryset = list_zones_for_membership(
            membership=membership,
            site_id=request.query_params.get("site_id"),
            search=request.query_params.get("search", "").strip(),
            status_value=status_value,
        )
        return _paginated_response(
            queryset=queryset,
            serializer_class=ZoneSerializer,
            request=request,
            context={"membership": membership},
        )

    def post(self, request):
        membership = require_company_permission(user=request.user, permission_code="zones.create")
        serializer = ZoneCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        zone = create_zone(company=membership.company, data=serializer.validated_data)
        return Response(ZoneSerializer(zone, context={"membership": membership}).data, status=status.HTTP_201_CREATED)


class ZoneDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, zone_id):
        membership = require_company_permission(user=request.user, permission_code="zones.view")
        zone = get_zone_for_membership(membership=membership, zone_id=zone_id, permission_code="zones.view")
        if not zone:
            raise ZoneNotFound()
        return Response(ZoneSerializer(zone, context={"membership": membership}).data)

    def patch(self, request, zone_id):
        permission_code = "zones.update"
        try:
            membership = require_company_permission(user=request.user, permission_code=permission_code)
        except PermissionDenied:
            if set(request.data.keys()) - ZONE_OPERATIONAL_FIELDS:
                raise
            permission_code = "zones.update_operational"
            membership = require_company_permission(user=request.user, permission_code=permission_code)

        zone = get_zone_for_membership(membership=membership, zone_id=zone_id, permission_code=permission_code)
        if not zone:
            raise ZoneNotFound()
        if zone.status == ZoneSerializer.Meta.model.Status.ARCHIVED or zone.site.status == SiteSerializer.Meta.model.Status.ARCHIVED:
            raise PermissionDenied()
        serializer = ZoneUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        zone = update_zone(zone=zone, data=serializer.validated_data)
        return Response(ZoneSerializer(zone, context={"membership": membership}).data)


class ZoneArchiveView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, zone_id):
        membership = require_company_permission(user=request.user, permission_code="zones.archive")
        zone = get_zone_for_membership(membership=membership, zone_id=zone_id, permission_code="zones.archive")
        if not zone:
            raise ZoneNotFound()
        return Response(ZoneSerializer(archive_zone(zone=zone), context={"membership": membership}).data)


class ZoneReactivateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, zone_id):
        membership = require_company_permission(user=request.user, permission_code="zones.update")
        zone = get_zone_for_membership(membership=membership, zone_id=zone_id, permission_code="zones.update")
        if not zone:
            raise ZoneNotFound()
        return Response(ZoneSerializer(activate_zone(zone=zone), context={"membership": membership}).data)


ZoneActivateView = ZoneReactivateView


class MembershipListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        membership = require_company_permission(user=request.user, permission_code="users.view")
        memberships = list_memberships_for_company(company=membership.company)
        return Response({"results": [serialize_membership(item, actor_membership=membership) for item in memberships]})


class InvitationListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        membership = require_company_permission(user=request.user, permission_code="invitations.view")
        invitations = list_invitations_for_company(company=membership.company)
        return Response(
            {
                "results": [
                    serialize_invitation(invitation, scopes=get_invitation_scopes(invitation=invitation))
                    for invitation in invitations
                ]
            }
        )

    def post(self, request):
        membership = require_company_permission(user=request.user, permission_code="users.invite")
        serializer = InvitationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        invitation = invite_company_member(
            company=membership.company,
            invited_by=request.user,
            email=serializer.validated_data["email"],
            first_name=serializer.validated_data.get("first_name", ""),
            last_name=serializer.validated_data.get("last_name", ""),
            role_code=serializer.validated_data["role_code"],
            site_ids=serializer.validated_data.get("site_ids", []),
            zone_ids=serializer.validated_data.get("zone_ids", []),
        )
        return Response(
            serialize_invitation(invitation, scopes=getattr(invitation, "_resolved_scopes", [])),
            status=status.HTTP_201_CREATED,
        )


class MembershipDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, membership_id):
        actor_membership = require_company_permission(user=request.user, permission_code="users.view")
        membership = get_membership_for_company(company=actor_membership.company, membership_id=membership_id)
        if not membership:
            raise MembershipNotFound()
        return Response(serialize_membership(membership, actor_membership=actor_membership))

    def patch(self, request, membership_id):
        actor_membership = require_company_permission(user=request.user, permission_code="users.update_role")
        membership = get_membership_for_company(company=actor_membership.company, membership_id=membership_id)
        if not membership:
            raise MembershipNotFound()
        serializer = MembershipUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        membership = update_member_role_and_scopes(
            membership=membership,
            role_code=serializer.validated_data["role_code"],
            site_ids=serializer.validated_data.get("site_ids", []),
            zone_ids=serializer.validated_data.get("zone_ids", []),
            actor=request.user,
        )
        return Response(serialize_membership(membership, actor_membership=actor_membership))


class MembershipSuspendView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, membership_id):
        actor_membership = require_company_permission(user=request.user, permission_code="users.suspend")
        membership = get_membership_for_company(company=actor_membership.company, membership_id=membership_id)
        if not membership:
            raise MembershipNotFound()
        return Response(serialize_membership(suspend_member(membership=membership), actor_membership=actor_membership))


class MembershipReactivateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, membership_id):
        actor_membership = require_company_permission(user=request.user, permission_code="users.reactivate")
        membership = get_membership_for_company(company=actor_membership.company, membership_id=membership_id)
        if not membership:
            raise MembershipNotFound()
        return Response(serialize_membership(reactivate_member(membership=membership), actor_membership=actor_membership))


class InvitationCancelView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, invitation_id):
        actor_membership = require_company_permission(user=request.user, permission_code="invitations.cancel")
        invitation = get_invitation_for_company(company=actor_membership.company, invitation_id=invitation_id)
        if not invitation:
            raise InvitationNotFound()
        invitation = cancel_invitation(invitation=invitation)
        return Response(serialize_invitation(invitation, scopes=get_invitation_scopes(invitation=invitation)))


class InvitationResendView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, invitation_id):
        actor_membership = require_company_permission(user=request.user, permission_code="invitations.resend")
        invitation = get_invitation_for_company(company=actor_membership.company, invitation_id=invitation_id)
        if not invitation:
            raise InvitationNotFound()
        invitation = resend_invitation(invitation=invitation)
        return Response(serialize_invitation(invitation, scopes=get_invitation_scopes(invitation=invitation)))


class InvitationValidateView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = InvitationValidateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        invitation = validate_company_invitation_token(raw_token=serializer.validated_data["token"])
        if not invitation:
            return Response({"valid": False})
        existing_user = User.objects.filter(email__iexact=invitation.invited_email).exists()
        return Response(
            {
                "valid": True,
                "invitation": serialize_invitation(invitation, scopes=get_invitation_scopes(invitation=invitation)),
                "existing_user": existing_user,
                "requires_password": not existing_user,
            }
        )


class InvitationAcceptView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = InvitationAcceptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        membership = accept_company_invitation(
            raw_token=serializer.validated_data["token"],
            password=serializer.validated_data.get("password"),
        )
        return Response(
            {
                "status": "accepted",
                "membership": serialize_membership(membership),
                "next_step": "LOGIN",
            }
        )


InvitationCreateView = InvitationListCreateView
