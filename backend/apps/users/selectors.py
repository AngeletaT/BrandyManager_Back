from django.contrib.auth import get_user_model


User = get_user_model()


def get_user_by_email(*, email):
    return User.objects.filter(email__iexact=email).first()


def user_exists_by_email(*, email):
    return User.objects.filter(email__iexact=email).exists()
