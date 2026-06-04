from paper.models import Paper
from researchhub_document.models import ResearchhubPost
from researchhub_document.related_models.constants.document_type import (
    PAPER,
    RESEARCHHUB_POST_DOCUMENT_TYPES,
)
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
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


def get_uni_doc_related_model(unified_document):
    if not isinstance(unified_document, ResearchhubUnifiedDocument):
        return None
    doc_type = unified_document.document_type
    if doc_type in RESEARCHHUB_POST_DOCUMENT_TYPES:
        return ResearchhubPost
    elif doc_type == PAPER:
        return Paper
    else:
        return None
