from rest_framework.permissions import BasePermission

from utils.http import DELETE, GET, POST, RequestMethods
from utils.permissions import AuthorizationBasedPermission


class UpdateAuthor(AuthorizationBasedPermission):
    message = "Action not permitted."

    def is_authorized(self, request, view, obj):
        if (
            (request.method == RequestMethods.PUT)
            or (request.method == RequestMethods.PATCH)
            or (request.method == RequestMethods.DELETE)
        ):
            return request.user == obj.user
        return True


class Censor(AuthorizationBasedPermission):
    message = "Need to be a moderator to censor users."

    def is_authorized(self, request, view, obj):
        return request.user.moderator


class IsModerator(AuthorizationBasedPermission):
    message = "Need to be a moderator."

    def has_permission(self, request, view):
        return request.user.moderator

    def is_authorized(self, request, view, obj):
        return request.user.moderator


class CreateOrViewOrRevokeUserApiToken(BasePermission):
    message = "Action not permitted"

    def has_object_permission(self, request, view, obj):
        user = request.user
        if user.is_anonymous:
            return False

        if obj.user == user and request.method == DELETE:
            return True

        return False

    def has_permission(self, request, view):
        user = request.user
        if user.is_anonymous:
            return False

        if request.method in (POST, GET, DELETE):
            return True

        return False


class UserIsEditor(BasePermission):
    message = "Need to be a hub editor to delete discussions"

    def has_object_permission(self, request, view, obj):
        user = request.user
        if user.is_anonymous:
            return False

        return user.is_hub_editor()

    def has_permission(self, request, view):
        user = request.user
        if user.is_anonymous:
            return False

        return user.is_hub_editor()


class RequestorIsOwnUser(BasePermission):
    message = "Permission Denied: Not own user"

    def has_permission(self, request, view):
        requestor = request.user
        if requestor.is_anonymous:
            return False

        target_user_id = request.data.get("target_user_id")
        return target_user_id == requestor.id


class DeleteUserPermission(BasePermission):
    message = "Permission Denied: Not own user or moderator"

    def has_object_permission(self, request, view, obj):
        user = request.user
        user_is_moderator = user.moderator

        if request.method == DELETE and (user_is_moderator or user == obj):
            return True
        return False


class DeleteAuthorPermission(BasePermission):
    message = "Permission Denied: User is not moderator"

    def has_object_permission(self, request, view, obj):
        user = request.user
        user_is_moderator = user.moderator

        if request.method == DELETE and user_is_moderator:
            return True
        return False


class HasVerificationPermission(BasePermission):
    message = "User verification denied"

    def has_permission(self, request, view):
        from user.models import UserApiToken

        user = request.user

        if user.is_anonymous:
            return False

        verification_tokens = user.api_keys.filter(
            name=UserApiToken.TEMPORARY_VERIFICATION_TOKEN
        )
        if not verification_tokens.exists():
            return False

        for verification_token in verification_tokens.iterator():
            if verification_token.has_expired:
                return False

        return True
