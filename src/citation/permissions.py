from rest_framework.permissions import BasePermission

from utils.http import RequestMethods


class UserIsAdminOfProject(BasePermission):
    message = "Permission Denied: Not requestor is not admin of the project"

    def has_permission(self, request, view):
        method = request.method
        if method == RequestMethods.DELETE:
            return True
        return False

    def has_object_permission(self, request, view, obj):
        requestor = request.user
        return obj.get_is_user_admin(requestor)
