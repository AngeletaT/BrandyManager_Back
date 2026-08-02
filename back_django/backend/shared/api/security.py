from django.conf import settings


def request_has_trusted_origin(*, request):
    origin = request.headers.get("Origin")
    if not origin:
        return True
    trusted_origins = set(settings.CORS_ALLOWED_ORIGINS) | set(settings.CSRF_TRUSTED_ORIGINS)
    return origin in trusted_origins
