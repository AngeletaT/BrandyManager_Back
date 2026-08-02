from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.authorization.models import CompanyRole, PlatformRole, UserPlatformRole
from apps.audit.models import AuditLog
from apps.organizations.models import CompanyMembership, MembershipGrant
from apps.organizations.services import transfer_membership_by_support_ticket
from apps.organizations.tests import factories as f
from apps.support.models import Incident
from apps.support.services import create_membership_transfer_request


class MembershipTransferRequestTests(TestCase):
    def setUp(self):
        self.source_company = f.company("source")
        self.target_company = f.company("target")
        self.owner_user = f.user("owner@example.com")
        self.member_user = f.user("member@example.com")
        self.internal_admin = f.user("internal-admin@example.com")
        self.owner_membership = f.membership(self.source_company, self.owner_user)
        self.member_membership = f.membership(self.source_company, self.member_user)
        self.company_scope = f.scope(self.source_company)
        self.owner_role = CompanyRole.objects.create(code="OWNER", name="Owner")
        self.manager_role = CompanyRole.objects.create(code="MANAGER", name="Manager")
        MembershipGrant.objects.create(
            membership=self.owner_membership,
            role=self.owner_role,
            scope=self.company_scope,
        )
        self.member_grant = MembershipGrant.objects.create(
            membership=self.member_membership,
            role=self.manager_role,
            scope=self.company_scope,
        )
        internal_role = PlatformRole.objects.create(code="SUPPORT_AGENT", name="Support Agent", is_system=True)
        UserPlatformRole.objects.create(user=self.internal_admin, role=internal_role)

    def test_owner_can_open_membership_transfer_request(self):
        incident = create_membership_transfer_request(
            owner_membership=self.owner_membership,
            membership_to_transfer=self.member_membership,
            target_company=self.target_company,
            requested_by=self.owner_user,
            reason="El usuario cambia de negocio.",
        )

        self.assertEqual(incident.incident_type, "MEMBERSHIP_TRANSFER_REQUEST")
        self.assertEqual(incident.metadata["membership_id"], str(self.member_membership.id))
        self.assertEqual(incident.metadata["target_company_id"], str(self.target_company.id))

    def test_non_owner_cannot_open_membership_transfer_request(self):
        with self.assertRaises(ValidationError):
            create_membership_transfer_request(
                owner_membership=self.member_membership,
                membership_to_transfer=self.member_membership,
                target_company=self.target_company,
                requested_by=self.member_user,
                reason="Intento no autorizado.",
            )

    def test_internal_admin_can_transfer_membership_from_valid_ticket(self):
        incident = create_membership_transfer_request(
            owner_membership=self.owner_membership,
            membership_to_transfer=self.member_membership,
            target_company=self.target_company,
            requested_by=self.owner_user,
            reason="Transferencia aprobada por owner.",
        )

        transferred = transfer_membership_by_support_ticket(
            membership=self.member_membership,
            target_company=self.target_company,
            support_incident=incident,
            performed_by=self.internal_admin,
            reason="Ticket validado por soporte.",
        )
        self.member_grant.refresh_from_db()
        incident.refresh_from_db()

        self.assertEqual(transferred.company_id, self.target_company.id)
        self.assertEqual(transferred.status, CompanyMembership.Status.INVITED)
        self.assertFalse(self.member_grant.is_active)
        self.assertEqual(incident.status, Incident.Status.RESOLVED)
        self.assertTrue(
            AuditLog.objects.filter(
                action="company_membership.transfer_by_support_ticket",
                entity_id=transferred.id,
            ).exists()
        )

    def test_user_without_internal_role_cannot_transfer_membership(self):
        incident = create_membership_transfer_request(
            owner_membership=self.owner_membership,
            membership_to_transfer=self.member_membership,
            target_company=self.target_company,
            requested_by=self.owner_user,
            reason="Transferencia aprobada por owner.",
        )

        with self.assertRaises(ValidationError):
            transfer_membership_by_support_ticket(
                membership=self.member_membership,
                target_company=self.target_company,
                support_incident=incident,
                performed_by=self.owner_user,
                reason="No es soporte interno.",
            )
