from researchhub_access_group.constants import ADMIN
from utils.permissions import AuthorizationBasedPermission
from utils.http import POST


class IsAdmin(AuthorizationBasedPermission):
    message = 'User is not an admin of the organization'

    def is_authorized(self, request, view, obj):
        access_group = obj.access_group
        user = request.user
        return access_group.permissions.filter(
            user=user,
            access_type=ADMIN
        ).exists()


class IsAdminOrCreateOnly(AuthorizationBasedPermission):
    message = 'User is not an admin of the organization'

    def is_authorized(self, request, view, obj):
        if request.method == POST:
            return True

        access_group = obj.access_group
        user = request.user
        return access_group.permissions.filter(
            user=user,
            access_type=ADMIN
        ).exists()


class HasAccessPermission(AuthorizationBasedPermission):
    message = ''

    def is_authorized(self, request, view, obj):
        pass
