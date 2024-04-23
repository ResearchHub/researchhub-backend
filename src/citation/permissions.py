from rest_framework.permissions import BasePermission

from user.models import Organization
from utils.http import RequestMethods


class UserIsAdminOfProject(BasePermission):
    message = "Permission Denied: requestor is not admin of the project"

    def has_permission(self, request, view):
        method = request.method
        if method == RequestMethods.DELETE or method == RequestMethods.POST:
            return True
        return False

    def has_object_permission(self, request, view, obj):
        requestor = request.user
        return obj.get_is_user_admin(requestor) or obj.user == requestor


class UserCanViewCitation(BasePermission):
    message = "User does not have permission to view citation"

    def has_object_permission(self, request, view, obj):
        if request.user.is_anonymous is False and obj.organization.org_has_user(
            request.user.id
        ):
            return True

        return False


class UserBelongsToOrganization(BasePermission):
    message = "User does not belong to organization"

    def has_permission(self, request, view):
        method = request.method

        if method in (
            RequestMethods.POST,
            RequestMethods.PATCH,
            RequestMethods.PUT,
            RequestMethods.DELETE,
            RequestMethods.GET,
        ):
            organization = getattr(request, "organization", None)
            if not organization:
                data_org_id = request.data.get(
                    "organization", None
                ) or request.data.get("organization_id", None)
                if data_org_id:
                    organization = Organization.objects.get(id=data_org_id)

            if not organization:
                return False

            return organization.org_has_user(request.user)

        return True
