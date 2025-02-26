from rest_framework.permissions import BasePermission

from paper.models import Paper
from researchhub.lib import get_document_id_from_path
from user.models import Author
from utils.permissions import AuthorizationBasedPermission, PermissionDenied


class EditorCensorDiscussion(BasePermission):
    message = "Need to be a hub editor to delete discussions"

    def has_object_permission(self, request, view, obj):
        user = request.user
        if user.is_anonymous:
            return False

        return user.is_hub_editor()


class CensorDiscussion(AuthorizationBasedPermission):
    message = "Need to be a moderator or owner of the post to delete discussions."

    def is_authorized(self, request, view, obj):
        return obj.created_by.id == request.user.id or request.user.moderator


class Vote(AuthorizationBasedPermission):
    message = "Can not vote on own content"

    def is_authorized(self, request, view, obj):
        if request.user == obj.created_by:
            raise PermissionDenied(detail=self.message)
        return True


class Endorse(AuthorizationBasedPermission):
    def is_authorized(self, request, view, obj):
        paper_id = get_document_id_from_path(request)
        paper = Paper.objects.get(pk=paper_id)
        author = Author.objects.get(user=request.user)
        return (author in paper.authors.all()) or (
            request.user in paper.moderators.all()
        )
