from researchhub_document.models import ResearchhubPost
from utils.permissions import AuthorizationBasedPermission


class HasDocumentEditingPermission(AuthorizationBasedPermission):
    message = "Need to be author or moderator to edit"

    def has_permission(self, request, view):
        if (
            view.action == "create"
            or view.action == "update"
            or view.action == "upsert"
        ):
            if request.data.get("post_id") is not None:
                post = ResearchhubPost.objects.get(id=request.data.get("post_id"))
                if post.created_by_id == request.user.id or request.user.moderator:
                    return True
                if post.note_id is not None:
                    return post.note.organization.org_has_member_user(request.user)
                return False

        return True
