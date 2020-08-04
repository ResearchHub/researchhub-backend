from rest_framework.exceptions import PermissionDenied  # noqa: F401
from rest_framework.permissions import BasePermission, SAFE_METHODS
from utils.http import RequestMethods


class ReadOnly(BasePermission):
    def has_permission(self, request, view):
        return request.method in SAFE_METHODS


class CreateOrUpdateIfActive(BasePermission):
    def has_permission(self, request, view):
        if (
            (request.method == RequestMethods.POST)
            or (request.method == RequestMethods.PATCH)
            or (request.method == RequestMethods.PUT)
        ):
            return request.user.is_active
        return True


class CreateOrReadOnly(BasePermission):
    def has_permission(self, request, view):
        return (
            (request.method in SAFE_METHODS)
            or (request.method == RequestMethods.POST)
        )


class CreateOrUpdateOrReadOnly(BasePermission):
    def has_permission(self, request, view):
        return (
            (request.method in SAFE_METHODS)
            or (request.method == RequestMethods.POST)
            or (request.method == RequestMethods.PATCH)
        )


class AuthorizationBasedPermission(BasePermission):
    class Meta:
        abstract = True

    def has_object_permission(self, request, view, obj):
        return (
            self.is_read_only_request(request)
            or self.is_authorized(request, view, obj)
        )

    def is_read_only_request(self, request):
        return request.method in SAFE_METHODS

    def is_authorized(self, request, view, obj):
        raise NotImplementedError


class RuleBasedPermission(BasePermission):
    class Meta:
        abstract = True

    def has_permission(self, request, view):
        if self.is_read_only_request(request):
            return True
        return self.satisfies_rule(request)

    def is_read_only_request(self, request):
        return request.method in SAFE_METHODS

    def satisfies_rule(self, request):
        raise NotImplementedError
