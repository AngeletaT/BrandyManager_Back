from django.urls import path

from apps.onboarding.views import OnboardingCompleteAPIView


urlpatterns = [
    path("complete/", OnboardingCompleteAPIView.as_view(), name="onboarding-complete"),
]
