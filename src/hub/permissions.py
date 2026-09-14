from rest_framework.permissions import BasePermission

from user.constants.gatekeeper_constants import PERMISSIONS_DASH
from user.related_models.gatekeeper_model import Gatekeeper


class IsModerator(BasePermission):
    """
    Allows access only to authenticated users who are moderators
    """

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.moderator)


class IsModeratorOrSuperEditor(BasePermission):
    """
    Allows access only to authenticated users who are moderators
    """

    def has_permission(self, request, view):
        user = request.user
        is_super_editor = Gatekeeper.objects.filter(
            email=user.email, type=PERMISSIONS_DASH
        ).exists()
        return bool(
            user and user.is_authenticated and (user.moderator or is_super_editor)
        )
