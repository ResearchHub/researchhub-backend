from rest_framework.permissions import BasePermission

from user.constants.gatekeeper_constants import PERMISSIONS_DASH
from user.models.gatekeeper_model import Gatekeeper
from utils.permissions import AuthorizationBasedPermission, RuleBasedPermission


class CreateHub(RuleBasedPermission):
    message = "Not enough reputation to create hub."

    def satisfies_rule(self, request):
        return request.user.reputation >= 100


class UpdateHub(RuleBasedPermission):
    message = "Must be moderator to edit hub"

    def has_permission(self, request, view):
        if view.action == "update" and (
            request.method == "PUT" or request.method == "PATCH"
        ):
            return (
                request.user.is_anonymous is False
                and request.user.is_authenticated
                and request.user.moderator
            )
        else:
            return True


class IsSubscribed(AuthorizationBasedPermission):
    message = "Must be subscribed."

    def is_authorized(self, request, view, obj):
        return request.user in obj.subscribers.all()


class IsNotSubscribed(AuthorizationBasedPermission):
    message = "Must not be subscribed."

    def is_authorized(self, request, view, obj):
        return request.user not in obj.subscribers.all()


class CensorHub(RuleBasedPermission):
    message = "Need to be a moderator to remove hubs."

    def satisfies_rule(self, request):
        if request.method == "DELETE":
            return (
                request.user.is_anonymous is False
                and request.user.is_authenticated
                and request.user.moderator
            )
        else:
            return False


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
