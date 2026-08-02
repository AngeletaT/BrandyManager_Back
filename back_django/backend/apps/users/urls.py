from django.urls import path

from apps.users.views import (
    EmailVerificationConfirmAPIView,
    EmailVerificationResendAPIView,
    PasswordResetConfirmAPIView,
    PasswordResetRequestAPIView,
    PasswordResetValidateAPIView,
    UserLoginAPIView,
    UserLogoutAPIView,
    UserMeAPIView,
    UserRegisterAPIView,
    UserTokenRefreshAPIView,
)


urlpatterns = [
    path("register/", UserRegisterAPIView.as_view(), name="user-register"),
    path("login/", UserLoginAPIView.as_view(), name="user-login"),
    path("token/refresh/", UserTokenRefreshAPIView.as_view(), name="user-token-refresh"),
    path("logout/", UserLogoutAPIView.as_view(), name="user-logout"),
    path("me/", UserMeAPIView.as_view(), name="user-me"),
    path("email-verification/resend/", EmailVerificationResendAPIView.as_view(), name="user-email-verification-resend"),
    path("email-verification/confirm/", EmailVerificationConfirmAPIView.as_view(), name="user-email-verification-confirm"),
    path("password-reset/request/", PasswordResetRequestAPIView.as_view(), name="user-password-reset-request"),
    path("password-reset/validate/", PasswordResetValidateAPIView.as_view(), name="user-password-reset-validate"),
    path("password-reset/confirm/", PasswordResetConfirmAPIView.as_view(), name="user-password-reset-confirm"),
]
