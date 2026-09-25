from django.conf import settings


def _cookie_kwargs():
    return {
        "httponly": True,
        "secure": settings.BM_DEVICE_REFRESH_COOKIE_SECURE,
        "samesite": settings.BM_DEVICE_REFRESH_COOKIE_SAMESITE,
        "path": settings.BM_DEVICE_REFRESH_COOKIE_PATH,
    }


def set_device_refresh_cookie(response, *, credential_id, raw_secret):
    response.set_cookie(
        settings.BM_DEVICE_REFRESH_COOKIE_NAME,
        f"{credential_id}.{raw_secret}",
        max_age=int(settings.BM_DEVICE_REFRESH_TOKEN_LIFETIME.total_seconds()),
        **_cookie_kwargs(),
    )


def clear_device_refresh_cookie(response):
    response.delete_cookie(
        settings.BM_DEVICE_REFRESH_COOKIE_NAME,
        samesite=settings.BM_DEVICE_REFRESH_COOKIE_SAMESITE,
        path=settings.BM_DEVICE_REFRESH_COOKIE_PATH,
    )
