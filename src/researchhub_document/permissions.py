from researchhub_document.models import ResearchhubPost
from utils.permissions import AuthorizationBasedPermission


class HasDocumentEditingPermission(AuthorizationBasedPermission):
    message = "Need to be author or moderator to edit"

    def has_permission(self, request, view):
        if (
            view.action == "create"
            or view.action == "update"
            or view.action == "upsert"
        ) and request.data.get("post_id") is not None:
            post = ResearchhubPost.objects.get(id=request.data.get("post_id"))
            return self.can_edit_post(post, request.user)

        return True

    @staticmethod
    def can_edit_post(post, user):
        """Apply the same editing rule outside the HTTP permission boundary."""
        if user is None or not user.is_authenticated:
            return False
        if post.created_by_id == user.id or user.moderator:
            return True
        if post.note_id is not None and post.note.organization is not None:
            return post.note.organization.org_has_member_user(user)
        return False
