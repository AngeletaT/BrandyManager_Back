from django.urls import path

from apps.organizations import views


urlpatterns = [
    path("company/", views.MyCompanyView.as_view(), name="organization-company"),
    path("sites/", views.SiteListCreateView.as_view(), name="organization-site-list"),
    path("sites/<uuid:site_id>/", views.SiteDetailView.as_view(), name="organization-site-detail"),
    path("sites/<uuid:site_id>/archive/", views.SiteArchiveView.as_view(), name="organization-site-archive"),
    path("sites/<uuid:site_id>/activate/", views.SiteActivateView.as_view(), name="organization-site-activate"),
    path("sites/<uuid:site_id>/reactivate/", views.SiteReactivateView.as_view(), name="organization-site-reactivate"),
    path("zones/", views.ZoneListCreateView.as_view(), name="organization-zone-list"),
    path("zones/<uuid:zone_id>/", views.ZoneDetailView.as_view(), name="organization-zone-detail"),
    path("zones/<uuid:zone_id>/archive/", views.ZoneArchiveView.as_view(), name="organization-zone-archive"),
    path("zones/<uuid:zone_id>/activate/", views.ZoneActivateView.as_view(), name="organization-zone-activate"),
    path("zones/<uuid:zone_id>/reactivate/", views.ZoneReactivateView.as_view(), name="organization-zone-reactivate"),
    path("members/", views.MembershipListView.as_view(), name="organization-member-list"),
    path("members/<uuid:membership_id>/", views.MembershipDetailView.as_view(), name="organization-member-detail"),
    path("members/<uuid:membership_id>/suspend/", views.MembershipSuspendView.as_view(), name="organization-member-suspend"),
    path("members/<uuid:membership_id>/reactivate/", views.MembershipReactivateView.as_view(), name="organization-member-reactivate"),
    path("memberships/", views.MembershipListView.as_view(), name="organization-membership-list"),
    path("memberships/<uuid:membership_id>/", views.MembershipDetailView.as_view(), name="organization-membership-detail"),
    path("memberships/<uuid:membership_id>/suspend/", views.MembershipSuspendView.as_view(), name="organization-membership-suspend"),
    path("memberships/<uuid:membership_id>/reactivate/", views.MembershipReactivateView.as_view(), name="organization-membership-reactivate"),
    path("invitations/", views.InvitationListCreateView.as_view(), name="organization-invitation-list"),
    path("invitations/", views.InvitationCreateView.as_view(), name="organization-invitation-create"),
    path("invitations/validate/", views.InvitationValidateView.as_view(), name="organization-invitation-validate"),
    path("invitations/accept/", views.InvitationAcceptView.as_view(), name="organization-invitation-accept"),
    path("invitations/<uuid:invitation_id>/cancel/", views.InvitationCancelView.as_view(), name="organization-invitation-cancel"),
    path("invitations/<uuid:invitation_id>/resend/", views.InvitationResendView.as_view(), name="organization-invitation-resend"),
]
