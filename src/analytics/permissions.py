from utils.http import POST
from utils.permissions import AuthorizationBasedPermission


class UpdateOrDelete(AuthorizationBasedPermission):
    message = 'User is not authorized.'

    def is_authorized(self, request, view, obj):
        if request.method == POST:
            return True
        return request.user.is_staff
