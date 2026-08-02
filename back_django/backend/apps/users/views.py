from django.conf import settings
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.cookies import delete_refresh_cookie, set_refresh_cookie
from apps.users.exceptions import OriginNotTrusted, SessionExpired
from apps.users.selectors import build_user_session_context
from apps.users.serializers import (
    CurrentUserResponseSerializer,
    EmailVerificationConfirmResponseSerializer,
    EmailVerificationConfirmSerializer,
    EmailVerificationResendResponseSerializer,
    EmailVerificationResendSerializer,
    PasswordResetConfirmResponseSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestResponseSerializer,
    PasswordResetRequestSerializer,
    PasswordResetValidateResponseSerializer,
    PasswordResetValidateSerializer,
    SessionResponseSerializer,
    UserLoginSerializer,
    UserRegisterResponseSerializer,
    UserRegisterSerializer,
)
from apps.users.services import (
    confirm_email_verification,
    confirm_password_reset,
    login_user,
    logout_user_session,
    password_reset_token_is_valid,
    refresh_user_session,
    register_client_user,
    request_password_reset,
    resend_email_verification,
)
from shared.api.security import request_has_trusted_origin


class UserRegisterAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = UserRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = register_client_user(data=serializer.validated_data)
        output = UserRegisterResponseSerializer(
            {
                "status": "verification_required",
                "email": user.email,
                "next_step": "VERIFY_EMAIL",
            }
        )

        return Response(output.data, status=status.HTTP_201_CREATED)


class UserLoginAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = UserLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        payload, refresh_token = login_user(data=serializer.validated_data)
        output = SessionResponseSerializer(payload)
        response = Response(output.data)
        set_refresh_cookie(response=response, refresh_token=refresh_token)
        return response


class UserTokenRefreshAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        if not request_has_trusted_origin(request=request):
            raise OriginNotTrusted()
        refresh_token = request.COOKIES.get(settings.BM_REFRESH_COOKIE_NAME)
        if not refresh_token:
            raise SessionExpired()

        payload, new_refresh_token = refresh_user_session(refresh_token=refresh_token)
        output = SessionResponseSerializer(payload)
        response = Response(output.data)
        set_refresh_cookie(response=response, refresh_token=new_refresh_token)
        return response


class UserLogoutAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        if not request_has_trusted_origin(request=request):
            raise OriginNotTrusted()
        refresh_token = request.COOKIES.get(settings.BM_REFRESH_COOKIE_NAME)
        logout_user_session(refresh_token=refresh_token)
        response = Response(status=status.HTTP_204_NO_CONTENT)
        delete_refresh_cookie(response=response)
        return response


class UserMeAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        payload = {
            "user": {
                "id": str(request.user.id),
                "email": request.user.email,
                "first_name": request.user.first_name,
                "last_name": request.user.last_name,
                "email_verified": bool(request.user.email_verified_at),
            },
            "context": build_user_session_context(user=request.user),
        }
        output = CurrentUserResponseSerializer(payload)
        return Response(output.data)


class EmailVerificationResendAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = EmailVerificationResendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        resend_email_verification(email=serializer.validated_data["email"])
        output = EmailVerificationResendResponseSerializer({"status": "accepted"})

        return Response(output.data, status=status.HTTP_202_ACCEPTED)


class EmailVerificationConfirmAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = EmailVerificationConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        confirm_email_verification(raw_token=serializer.validated_data["token"])
        output = EmailVerificationConfirmResponseSerializer(
            {
                "status": "verified",
                "next_step": "ONBOARDING",
            }
        )

        return Response(output.data)


class PasswordResetRequestAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        request_password_reset(email=serializer.validated_data["email"])
        output = PasswordResetRequestResponseSerializer({"status": "accepted"})
        return Response(output.data, status=status.HTTP_202_ACCEPTED)


class PasswordResetValidateAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetValidateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        output = PasswordResetValidateResponseSerializer(
            {"valid": password_reset_token_is_valid(raw_token=serializer.validated_data["token"])}
        )
        return Response(output.data)


class PasswordResetConfirmAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        confirm_password_reset(
            raw_token=serializer.validated_data["token"],
            password=serializer.validated_data["password"],
        )
        output = PasswordResetConfirmResponseSerializer({"status": "password_updated"})
        return Response(output.data)
