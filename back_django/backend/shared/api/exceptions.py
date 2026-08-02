from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.views import exception_handler

from shared.api.responses import error_response


class DomainError(Exception):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "domain_error"
    message = "No se pudo completar la operacion."
    fields = {}
    extra = {}

    def __init__(self, *, code=None, message=None, fields=None, status_code=None, extra=None):
        self.code = code or self.code
        self.message = message or self.message
        self.fields = fields or {}
        self.extra = extra or {}
        self.status_code = status_code or self.status_code
        super().__init__(self.message)


def custom_exception_handler(exc, context):
    if isinstance(exc, DomainError):
        return error_response(
            code=exc.code,
            message=exc.message,
            fields=exc.fields,
            status_code=exc.status_code,
            extra=exc.extra,
        )
    if isinstance(exc, DjangoValidationError):
        return error_response(
            code="validation_error",
            message="Los datos enviados no son validos.",
            fields={"non_field_errors": exc.messages},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    response = exception_handler(exc, context)
    if response is None:
        return None

    if "error" in response.data:
        return response

    fields = response.data if isinstance(response.data, dict) else {}
    detail = response.data.get("detail") if isinstance(response.data, dict) else None
    message = str(detail) if detail else "Los datos enviados no son validos."
    response.data = {
        "error": {
            "code": getattr(exc, "default_code", "api_error"),
            "message": message,
            "fields": fields,
        }
    }
    return response
