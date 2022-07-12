from rest_framework.permissions import BasePermission

from researchhub.settings import DIST_WHITELIST
from utils.http import RequestMethods
from utils.permissions import AuthorizationBasedPermission


class UpdateOrDeleteWithdrawal(AuthorizationBasedPermission):
    message = "Action not permitted."

    def is_authorized(self, request, view, obj):
        method = request.method
        user = request.user
        if (
            (method == RequestMethods.PUT)
            or (method == RequestMethods.PATCH)
            or (method == RequestMethods.DELETE)
        ):
            return user == obj.user
        return True


class DistributionWhitelist(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if user.is_anonymous:
            return False

        if user.email in DIST_WHITELIST:
            return True
        return False


class UserBounty(BasePermission):
    def has_permission(self, request, view):
        method = request.method
        if method == RequestMethods.POST or method == RequestMethods.DELETE:
            return True
        return False

    def has_object_permission(self, request, view, obj):
        return obj.created_by == request.user
