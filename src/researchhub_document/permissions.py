from hypothesis.related_models.hypothesis import Hypothesis
from paper.models import Paper
from researchhub_document.models import ResearchhubPost
from researchhub_document.models.constants.document_type import (
    HYPOTHESIS,
    PAPER,
    RESEARCHHUB_POST_DOCUMENT_TYPES,
)
from researchhub_document.models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from utils.permissions import AuthorizationBasedPermission


class HasDocumentCensorPermission(AuthorizationBasedPermission):
    message = "Need to be author or moderator to delete"

    def is_authorized(self, request, view, obj):
        if request.user.is_authenticated is False:
            return False

        doc = None
        is_author = False
        requestor = request.user

        if isinstance(obj, ResearchhubUnifiedDocument):
            uni_doc_model = get_uni_doc_related_model(obj)
            doc = (
                uni_doc_model.objects.get(unified_document_id=obj.id)
                if uni_doc_model is not None
                else None
            )
        elif isinstance(obj, Paper):
            doc = Paper.objects.get(id=obj.id)
        else:
            return False

        if doc is None:
            return False

        if isinstance(doc, Paper):
            is_author = doc.uploaded_by_id == requestor.id
        else:
            is_author = doc.created_by_id == requestor.id

        doc_hubs = doc.unified_document.hubs.all()
        is_requestor_appropriate_editor = requestor.is_hub_editor_of(
            doc_hubs,
        )
        if (
            requestor.moderator
            or is_requestor_appropriate_editor  # moderators serve as site admin
            or is_author
        ):
            return True

        return False


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
                if (
                    post.created_by_id == request.user.id
                    or request.user.moderator
                    or post.note.organization.org_has_member_user(request.user)
                ):
                    return True
                else:
                    return False
            elif request.data.get("hypothesis_id") is not None:
                hypothesis = Hypothesis.objects.get(
                    id=request.data.get("hypothesis_id")
                )
                if (
                    hypothesis.created_by_id == request.user.id
                    or request.user.moderator
                ):
                    return True
                else:
                    return False

        return True


def get_uni_doc_related_model(unified_document):
    if not isinstance(unified_document, ResearchhubUnifiedDocument):
        return None
    doc_type = unified_document.document_type
    if doc_type in RESEARCHHUB_POST_DOCUMENT_TYPES:
        return ResearchhubPost
    elif doc_type == HYPOTHESIS:
        return Hypothesis
    elif doc_type == PAPER:
        return Paper
    else:
        return None
