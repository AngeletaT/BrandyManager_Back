from django.contrib.auth import authenticate, get_user_model
from django.db import transaction
from rest_framework.exceptions import AuthenticationFailed, ValidationError
from rest_framework_simplejwt.tokens import RefreshToken

from apps.users.selectors import user_exists_by_email


UserModel = get_user_model()


def build_user_tokens(*, user):
    refresh = RefreshToken.for_user(user)

    return {
        "refresh": str(refresh),
        "access": str(refresh.access_token),
    }


@transaction.atomic
def register_client_user(*, data):
    email = data["email"]

    if user_exists_by_email(email=email):
        raise ValidationError({"email": ["Ya existe un usuario con este email."]})

    user = UserModel.objects.create_user(
        email=email,
        password=data["password"],
        first_name=data.get("first_name", ""),
        last_name=data.get("last_name", ""),
    )

    return user, build_user_tokens(user=user)


def login_user(*, data):
    user = authenticate(email=data["email"], password=data["password"])

    if user is None:
        raise AuthenticationFailed("Credenciales incorrectas.")

    if not user.is_active:
        raise AuthenticationFailed("El usuario esta desactivado.")

    return user, build_user_tokens(user=user)
