from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsOwnerOrReadOnly(BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS and getattr(obj, "is_public", False):
            return True

        return getattr(obj, "created_by_id", None) == getattr(request.user, "id", None)
