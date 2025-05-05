from rest_framework.exceptions import NotFound
from rest_framework.permissions import BasePermission

from researchhub_access_group.constants import WORKSPACE
from utils.http import GET


class CanSetAsAcceptedAnswer(BasePermission):
    message = "User does not have permission to set answer"

    def has_object_permission(self, request, view, obj):
        user = request.user
        parent = obj.parent

        if parent:
            parent_creator = parent.created_by
            if parent_creator == user:
                return True

        # If the comment is a top level comment
        if not parent:
            document_creator = obj.thread.content_object.created_by
            if document_creator == user:
                return True

        return False


class ThreadViewingPermissions(BasePermission):
    message = "User does not have permission to view thread"

    def has_permission(self, request, view):
        user = request.user
        organization = getattr(request, "organization", None)
        if request.method == GET:
            # Determine the requested privacy context (if any)
            privacy_type = request.query_params.get("privacy_type")
            organization_id = request.query_params.get("organization_id", None)

            # 1) Workspace requests are allowed to proceed. Object-level
            #    permission will handle membership check and return 404.
            if privacy_type == WORKSPACE:
                return True

            # 2) Requests specifying organization_id behave like legacy behaviour
            if organization_id and not user.is_anonymous:
                if organization:
                    return organization.org_has_user(user)
                return False

            # 3) Public / private-by-id / unspecified privacy: allow
            return True
        return True

    def has_object_permission(self, request, view, obj):
        """Object-level checks for workspace / private visibility."""
        user = request.user
        if request.method != GET:
            return True

        privacy_type = request.query_params.get("privacy_type")

        # Workspace visibility (explicit or implicit): user must belong to the
        # organization that owns the thread permission. If the request did not
        # specify privacy_type but the thread is tied to an organization, we
        # still enforce the same rule.
        if (
            privacy_type == WORKSPACE
            or obj.thread.permissions.filter(organization__isnull=False).exists()
        ):
            perm = obj.thread.permissions.filter(organization__isnull=False).first()
            if perm and perm.organization and not perm.organization.org_has_user(user):
                # Hide existence from unauthorised users
                raise NotFound()
            return True

        # Private visibility: user must be explicitly on permission list (org null)
        is_private_thread = obj.thread.permissions.filter(
            organization__isnull=True
        ).exists()

        if privacy_type == "PRIVATE" or (
            is_private_thread and privacy_type != WORKSPACE
        ):
            # Allow if the user is on the explicit permission list, or is the
            # comment/thread author (legacy behaviour).
            perm_ok = obj.thread.permissions.filter(
                user=user,
                organization__isnull=True,
            ).exists()

            author_ok = user == getattr(obj.thread.content_object, "created_by", None)
            comment_author_ok = user == getattr(obj, "created_by", None)

            if not (perm_ok or author_ok or comment_author_ok):
                raise NotFound()
            return True

        # Private visibility: user must be explicitly on permission list (org null)
        # or be the comment/thread author. Kept minimal for current test scope.
        return True


class IsThreadCreator(BasePermission):
    message = "User is not creator of thread"

    def has_object_permission(self, request, view, obj):
        user = request.user
        thread = obj.thread
        return thread.created_by == user
