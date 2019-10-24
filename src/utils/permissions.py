from rest_framework.permissions import BasePermission, SAFE_METHODS


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
        return (
            bool(request.user and request.user.is_authenticated)
            and self.satisfies_rule(request)
        )

    def is_read_only_request(self, request):
        return request.method in SAFE_METHODS

    def satisfies_rule(self, request):
        raise NotImplementedError
