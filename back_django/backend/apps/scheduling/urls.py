from django.urls import path

from apps.scheduling import views


urlpatterns = [
    path("schedules/", views.ScheduleListCreateView.as_view(), name="schedule-list"),
    path("schedules/resolve/", views.ScheduleResolveView.as_view(), name="schedule-resolve"),
    path("schedules/<uuid:schedule_id>/", views.ScheduleDetailView.as_view(), name="schedule-detail"),
    path("schedules/<uuid:schedule_id>/blocks/", views.ScheduleBlockListCreateView.as_view(), name="schedule-block-list"),
    path("schedules/<uuid:schedule_id>/blocks/<uuid:block_id>/", views.ScheduleBlockDetailView.as_view(), name="schedule-block-detail"),
    path("schedules/<uuid:schedule_id>/exceptions/", views.ScheduleExceptionListCreateView.as_view(), name="schedule-exception-list"),
    path("schedules/<uuid:schedule_id>/exceptions/<uuid:exception_id>/", views.ScheduleExceptionDetailView.as_view(), name="schedule-exception-detail"),
    path("schedules/<uuid:schedule_id>/assignments/", views.ScheduleAssignmentListCreateView.as_view(), name="schedule-assignment-list"),
    path("schedules/<uuid:schedule_id>/assignments/<uuid:assignment_id>/", views.ScheduleAssignmentDetailView.as_view(), name="schedule-assignment-detail"),
    path("schedules/<uuid:schedule_id>/publish/", views.SchedulePublishView.as_view(), name="schedule-publish"),
    path("schedules/<uuid:schedule_id>/archive/", views.ScheduleArchiveView.as_view(), name="schedule-archive"),
    path("schedules/<uuid:schedule_id>/reactivate/", views.ScheduleReactivateView.as_view(), name="schedule-reactivate"),
    path("schedules/<uuid:schedule_id>/disable/", views.ScheduleDisableView.as_view(), name="schedule-disable"),
    path("schedules/<uuid:schedule_id>/occurrences/", views.ScheduleOccurrencesView.as_view(), name="schedule-occurrences"),
]

