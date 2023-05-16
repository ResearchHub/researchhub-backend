from rest_framework.permissions import BasePermission


class UserIsAdminOfProject(BasePermission):
    message = "Permission Denied: Not own admin"

    def has_permission(self, request, view):
        requestor = request.user
        if requestor.is_anonymous:
            return False

        target_user_id = request.data.get("target_user_id")
        return target_user_id == requestor.id
