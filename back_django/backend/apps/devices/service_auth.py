import hmac

from django.conf import settings
from rest_framework.permissions import BasePermission


class HasGoServiceToken(BasePermission):
    message = "El servicio no esta autorizado."

    def has_permission(self, request, view):
        configured_token = settings.BM_GO_SERVICE_TOKEN
        supplied_token = request.headers.get("X-BrandyManager-Service-Token", "")
        return bool(configured_token and supplied_token and hmac.compare_digest(configured_token, supplied_token))
