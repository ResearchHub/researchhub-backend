from rest_framework.permissions import BasePermission

from utils.http import POST


class IsOrganizationAdmin(BasePermission):
    # This permission is used for Organization based views

    message = 'User is not an admin of the organization'

    def has_object_permission(self, request, view, obj):
        access_group = obj.access_group
        user = request.user
        return access_group.has_admin_user(user)


class IsAdminOrCreateOnly(BasePermission):
    message = 'User is not an admin of the organization'

    def has_object_permission(self, request, view, obj):
        if request.method == POST:
            return True

        user = request.user
        return obj.org_has_admin_user(user)


class IsOrganizationUser(BasePermission):
    message = 'User is not an admin of the organization'

    def has_object_permission(self, request, view, obj):
        if request.method == POST:
            return True

        user = request.user
        return obj.org_has_user(user)


class HasAdminPermission(BasePermission):
    # This permission is used for unified documents

    message = 'User does not have permission to view or create'

    def has_permission(self, request, view):
        return True

    def has_object_permission(self, request, view, obj):
        if not hasattr(obj, 'unified_document'):
            raise Exception('Object has no reference to unified document')

        unified_document = obj.unified_document
        access_groups = unified_document.access_groups
        return access_groups.has_admin_user(request.user)


class HasAccessPermission(BasePermission):
    # This permission is used for unified documents

    message = 'User does not have permission to view or create'

    def has_object_permission(self, request, view, obj):
        if not hasattr(obj, 'unified_document'):
            raise Exception('Object has no reference to unified document')

        unified_document = obj.unified_document
        access_groups = unified_document.access_groups
        return access_groups.has_user(request.user)
