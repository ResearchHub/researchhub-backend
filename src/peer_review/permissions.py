from lib2to3.pytree import Base
from rest_framework.permissions import BasePermission
from researchhub_document.models import (
    ResearchhubUnifiedDocument
)
from peer_review.models import PeerReviewRequest


class IsAllowedToRequest(BasePermission):
    message = 'Only authors are allowed to request peer reviews'

    def has_permission(self, request, view):
        requested_by_user = request.user
        uni_doc = ResearchhubUnifiedDocument.objects.get(id=request.data['unified_document'])

        is_author_requesting_review = uni_doc.authors.filter(
            id=requested_by_user.author_profile.id
        ).exists()

        if is_author_requesting_review or requested_by_user.moderator:
            return True

        return False


class IsAllowedToInvite(BasePermission):
    message = 'You are not allowed to invite peer reviewers'

    def has_permission(self, request, view):
        if request.user.moderator:
            return True

        return False


class IsAllowedToAcceptInvite(BasePermission):
    message = 'You cannot accept this invite. Please make sure you are logged into the right account.'

    def has_object_permission(self, request, view, obj):
        if obj.recipient_email == request.user.email:
            return True

        return False


class IsAllowedToList(BasePermission):
    message = 'You do not have permission to view this'

    def has_permission(self, request, view):
        if request.method == 'GET' and view.action == 'list':
            return True

        return False


class IsAllowedToRetrieve(BasePermission):
    message = 'You do not have permission to view this'

    def has_permission(self, request, view):
        if request.method == 'GET' and view.action == 'retrieve':
            if request.user.moderator:
                return True

        return False

class IsAllowedToCreateDecision(BasePermission):
    message = 'You do not have permission to do this'

    def has_object_permission(self, request, view, obj):
        if obj.assigned_user.id == request.user.id:
            return True

        return False

class IsAllowedToCreateOrUpdatePeerReview(BasePermission):
    def has_permission(self, request, view):
        if request.method == 'PUT' or request.method == 'POST':
            return False

        return True

class IsAllowedToCreateOrUpdatePeerReviewInvite(BasePermission):
    def has_permission(self, request, view):
        if request.method == 'PUT' or request.method == 'POST':
            return False

        return True

class IsAllowedToCreateOrUpdatePeerReviewRequest(BasePermission):
    def has_permission(self, request, view):
        if request.method == 'PUT' or request.method == 'POST':
            return False

        return True