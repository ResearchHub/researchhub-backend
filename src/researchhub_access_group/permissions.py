from utils.permissions import AuthorizationBasedPermission


class IsAdmin(AuthorizationBasedPermission):
    message = 'User is not an admin of the organization'

    def is_authorized(self, request, view, obj):
        access_group = obj.access_group
        user_id = request.user.id
        return access_group.admins.filter(id=user_id).exists()
