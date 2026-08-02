from rest_framework.response import Response


def error_response(*, code, message, status_code, fields=None, extra=None):
    error = {
        "code": code,
        "message": message,
        "fields": fields or {},
    }
    if extra:
        error.update(extra)
    return Response(
        {"error": error},
        status=status_code,
    )
