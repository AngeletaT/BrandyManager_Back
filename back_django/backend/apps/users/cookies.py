from django.conf import settings


def set_refresh_cookie(*, response, refresh_token):
    response.set_cookie(
        key=settings.BM_REFRESH_COOKIE_NAME,
        value=refresh_token,
        max_age=int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds()),
        httponly=settings.BM_REFRESH_COOKIE_HTTP_ONLY,
        secure=settings.BM_REFRESH_COOKIE_SECURE,
        samesite=settings.BM_REFRESH_COOKIE_SAMESITE,
        path=settings.BM_REFRESH_COOKIE_PATH,
    )


def delete_refresh_cookie(*, response):
    response.delete_cookie(
        key=settings.BM_REFRESH_COOKIE_NAME,
        path=settings.BM_REFRESH_COOKIE_PATH,
        samesite=settings.BM_REFRESH_COOKIE_SAMESITE,
    )
