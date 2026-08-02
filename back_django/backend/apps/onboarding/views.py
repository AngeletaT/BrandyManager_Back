from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.onboarding.serializers import OnboardingCompleteResponseSerializer, OnboardingCompleteSerializer
from apps.onboarding.services import complete_client_onboarding


class OnboardingCompleteAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = OnboardingCompleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = complete_client_onboarding(user=request.user, data=serializer.validated_data)
        output = OnboardingCompleteResponseSerializer(result)
        return Response(output.data, status=status.HTTP_201_CREATED)
