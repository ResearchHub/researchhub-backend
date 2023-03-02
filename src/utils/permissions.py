from rest_framework.exceptions import PermissionDenied  # noqa: F401
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework_api_key.permissions import BaseHasAPIKey

from researchhub.settings import ASYNC_SERVICE_API_KEY
from user.models import UserApiToken
from utils.http import RequestMethods


class ReadOnly(BasePermission):
    def has_permission(self, request, view):
        return request.method in SAFE_METHODS


class UserNotSpammer(BasePermission):
    def has_permission(self, request, view):
        return not request.user.probable_spammer


class CreateOrUpdateIfAllowed(BasePermission):
    def has_permission(self, request, view):
        if (request.method not in SAFE_METHODS) and request.user.is_authenticated:
            return request.user.is_active and (not request.user.is_suspended)
        return True


class CreateOrReadOnly(BasePermission):
    def has_permission(self, request, view):
        return (request.method in SAFE_METHODS) or (
            request.method == RequestMethods.POST
        )


class PostOnly(BasePermission):
    def has_permission(self, request, view):
        return request.method == RequestMethods.POST


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
        return self.is_read_only_request(request) or self.is_authorized(
            request, view, obj
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


class APIPermission(BasePermission):
    def has_permission(self, request, view):
        return request.headers.get("researchhub-async-api-key") == ASYNC_SERVICE_API_KEY


class HasAPIKey(BaseHasAPIKey):
    model = UserApiToken
