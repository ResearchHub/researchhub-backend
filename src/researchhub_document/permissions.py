from django.contrib.contenttypes.models import ContentType

from hub.models import Hub
from hypothesis.related_models.hypothesis import Hypothesis
from paper.models import Paper
from researchhub_access_group.constants import EDITOR
from researchhub_document.related_models.constants.document_type import (
    DISCUSSION,
    HYPOTHESIS,
    PAPER,
)
from researchhub_document.models import (
    ResearchhubPost
)
from utils.permissions import AuthorizationBasedPermission


class HasDocumentCensorPermission(AuthorizationBasedPermission):
    message = 'Need to be author or moderator to delete'

    def is_authorized(self, request, view, obj):
        if request.user.is_authenticated is False:
            return False

        document_type = obj.document_type
        doc = None
        if document_type == DISCUSSION:
            doc = ResearchhubPost.objects.get(unified_document_id=obj.id)
        elif document_type == HYPOTHESIS:
            doc = Hypothesis.objects.get(unified_document_id=obj.id)
        elif document_type == PAPER:
            doc = Paper.objects.get(id=obj.id)

        if (doc is None):
            return False

        requestor = request.user
        is_requestor_appropriate_editor = is_hub_editor(
            requestor,
            doc.hubs,
        )
        if (
            requestor.user.moderator or  # moderators serve as site admin
            is_requestor_appropriate_editor or
            doc.created_by_id == requestor.id
        ):
            return True

        return False


class HasDocumentEditingPermission(AuthorizationBasedPermission):
    message = 'Need to be author or moderator to edit'

    def has_permission(self, request, view):
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


def is_hub_editor(requestor_user, hubs):
    hub_content_type = ContentType.objects.get_for_model(Hub)
    return requestor_user.permissions.filter(
        access_type=EDITOR,
        content_type=hub_content_type,
        object_id__in=hubs.values_list('id', flat=True),
    ).exists()
