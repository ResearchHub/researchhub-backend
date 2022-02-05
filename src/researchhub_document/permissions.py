from utils.permissions import AuthorizationBasedPermission
from utils.http import PATCH, POST, PUT, GET, DELETE
from researchhub_document.related_models.constants.document_type import (
    HYPOTHESIS,
    DISCUSSION,
)
from hypothesis.related_models.hypothesis import Hypothesis
from researchhub_document.models import (
    ResearchhubPost
)

class HasDocumentCensorPermission(AuthorizationBasedPermission):
    message = 'Need to be author or moderator to delete'

    def is_authorized(self, request, view, obj):
        if request.user.is_authenticated is False:
            return False

        model = None
        if obj.document_type == DISCUSSION:
            model = ResearchhubPost
        elif obj.document_type == HYPOTHESIS:
            model = Hypothesis

        doc = model.objects.get(unified_document_id=obj.id)
        if doc.created_by_id == request.user.id or request.user.moderator:
            return True

        return False


class HasDocumentEditingPermission(AuthorizationBasedPermission):
    message = 'Need to be author or moderator to edit'

    def has_permission(self, request, view):
        # import pdb; pdb.set_trace()
        if view.action == 'create' or view.action == 'update' or view.action == 'upsert':
            if request.data.get('post_id') is not None:
                post = ResearchhubPost.objects.get(id=request.data.get('post_id'))
                if post.created_by_id == request.user.id or request.user.moderator:
                    return True
                else:
                    return False
            elif request.data.get('hypothesis_id') is not None:
                hypothesis = Hypothesis.objects.get(id=request.data.get('hypothesis_id'))
                if hypothesis.created_by_id == request.user.id or request.user.moderator:
                    return True
                else:
                    return False

        return True
