from rest_framework import permissions
from urllib.parse import urlparse
from researchhub.settings import (
    APP_ENV
)

class ApiPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if APP_ENV == "development":
            return True
        else:
            try:
                host = request.get_host()
                domain = urlparse(host).netloc
                if domain.endswith("researchhub.com"):
                    return True
            except:
                return False

        return False