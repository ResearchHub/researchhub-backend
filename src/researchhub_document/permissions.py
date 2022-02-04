from rest_framework.permissions import BasePermission
from utils.http import PATCH, POST, PUT, GET, DELETE
from researchhub_document.related_models.constants.document_type import (
    HYPOTHESIS,
    DISCUSSION,
)
from researchhub_document.models import (
    ResearchhubPost
)


class HasDocumentEditingPermission(BasePermission):
    message = 'Need to be a moderator or owner to edit'

    def has_object_permission(self, request, view, obj):

        if request.method == PATCH or request.method == DELETE:
            if obj.document_type == DISCUSSION:
                post = ResearchhubPost.objects.get(unified_document_id=obj.id)
                if (
                    request.user.is_authenticated and
                    (post.created_by_id == request.user.id or request.user.moderator)
                ):
                    return True
                else:
                    return False
        else:
            return False
