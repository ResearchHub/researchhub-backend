from rest_framework.permissions import SAFE_METHODS, BasePermission


class IsObjectOwner(BasePermission):
    message = "Invalid base permission"

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True

        user = request.user
        obj_user = getattr(obj, "created_by", None) or getattr(obj, "user", None)
        if obj_user == user:
            return True

        return False


class IsObjectOwnerOrModerator(IsObjectOwner):
    message = "Invalid base permission"

    def has_object_permission(self, request, view, obj):
        object_owner_permission = super().has_object_permission(request, view, obj)
        if request.user.moderator:
            return True
        return object_owner_permission
