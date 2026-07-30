from rest_framework.permissions import AllowAny
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.serializers import (
    AuthResponseSerializer,
    UserLoginSerializer,
    UserRegisterSerializer,
)
from apps.users.services import login_user, register_client_user


class UserRegisterAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = UserRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user, tokens = register_client_user(data=serializer.validated_data)
        output = AuthResponseSerializer({"user": user, "tokens": tokens})

        return Response(output.data, status=status.HTTP_201_CREATED)


class UserLoginAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = UserLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user, tokens = login_user(data=serializer.validated_data)
        output = AuthResponseSerializer({"user": user, "tokens": tokens})

        return Response(output.data)
