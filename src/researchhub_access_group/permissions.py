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
    message = 'User does not have permission to view or create'

    def is_authorized(self, request, view, obj):
        # import pdb; pdb.set_trace()
        if not hasattr(obj, 'unified_document'):
            raise Exception('Object has no reference to unified document')

        unified_document = obj.unified_document
        access_groups = unified_document.access_groups
        user_in_permissions = access_groups.filter(
            permissions__user=request.user
        )
        return user_in_permissions.exists()
