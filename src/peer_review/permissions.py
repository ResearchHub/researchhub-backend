from rest_framework.permissions import BasePermission
from researchhub_document.models import (
    ResearchhubUnifiedDocument
)


class IsAllowedToRequest(BasePermission):
    message = 'Only authors are allowed to request peer reviews'

    def has_permission(self, request, view):
        requested_by_user = request.user
        uni_doc = ResearchhubUnifiedDocument.objects.get(id=request.data['unified_document'])

        is_author_requesting_review = uni_doc.authors.filter(
            id=requested_by_user.id
        ).exists()

        if is_author_requesting_review or requested_by_user.moderator:
            return True

        return False
