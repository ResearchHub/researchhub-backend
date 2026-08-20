from rest_framework.permissions import SAFE_METHODS, BasePermission


class ReadOnly(BasePermission):
    def has_permission(self, request, view):
        return request.method in SAFE_METHODS


class UserNotSpammer(BasePermission):
    def has_permission(self, request, view):
        return not request.user.is_suspended


class CreateOrUpdateIfAllowed(BasePermission):
    def has_permission(self, request, view):
        if (request.method not in SAFE_METHODS) and request.user.is_authenticated:
            return request.user.is_active and not request.user.is_suspended
        return True


class CreateOrReadOnly(BasePermission):
    def has_permission(self, request, view):
        return (request.method in SAFE_METHODS) or (request.method == "POST")


class PostOnly(BasePermission):
    def has_permission(self, request, view):
        return request.method == "POST"


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
