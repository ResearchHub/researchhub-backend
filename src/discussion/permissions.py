from rest_framework.permissions import BasePermission

from hypothesis.models import Citation
from hypothesis.related_models.hypothesis import Hypothesis
from paper.models import Paper
from researchhub.lib import get_document_id_from_path
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from user.models import Author
from utils.permissions import (
    AuthorizationBasedPermission,
    PermissionDenied,
    RuleBasedPermission,
)


class EditorCensorDiscussion(BasePermission):
    message = "Need to be a hub editor to delete discussions"

    def has_object_permission(self, request, view, obj):
        user = request.user
        if user.is_anonymous:
            return False

        return user.is_hub_editor()


class CensorDiscussion(AuthorizationBasedPermission):
    message = "Need to be a moderator to delete discussions."

    def is_authorized(self, request, view, obj):
        return obj.created_by.id == request.user.id or request.user.moderator


class CreateDiscussionComment(RuleBasedPermission):
    message = "Not enough reputation to create comment."

    def satisfies_rule(self, request):
        return request.user.reputation >= 1


class CreateDiscussionReply(RuleBasedPermission):
    message = "Not enough reputation to create reply."

    def satisfies_rule(self, request):
        return request.user.reputation >= 1


class CreateDiscussionThread(RuleBasedPermission):
    message = "Not enough reputation to create thread."

    def satisfies_rule(self, request):
        return request.user.reputation >= 1


class UpdateDiscussionComment(AuthorizationBasedPermission):
    message = "Action not permitted."

    def is_authorized(self, request, view, obj):
        return obj.created_by == request.user and obj.is_removed is False


class UpdateDiscussionReply(AuthorizationBasedPermission):
    message = "Action not permitted."

    def is_authorized(self, request, view, obj):
        return obj.created_by == request.user and obj.is_removed is False


class UpdateDiscussionThread(AuthorizationBasedPermission):
    message = "Action not permitted."

    def is_authorized(self, request, view, obj):
        return obj.created_by == request.user and obj.is_removed is False


class FlagDiscussionComment(RuleBasedPermission):
    message = "Not enough reputation to flag comment."

    def satisfies_rule(self, request):
        return request.user.reputation >= 1 and not request.user.is_suspended


class FlagDiscussionReply(RuleBasedPermission):
    message = "Not enough reputation to flag reply."

    def satisfies_rule(self, request):
        return request.user.reputation >= 1 and not request.user.is_suspended


class FlagDiscussionThread(RuleBasedPermission):
    message = "Not enough reputation to flag thread."

    def satisfies_rule(self, request):
        return request.user.reputation >= 1 and not request.user.is_suspended


class Vote(AuthorizationBasedPermission):
    message = "Can not vote on own content"

    def is_authorized(self, request, view, obj):
        if request.user == obj.created_by and type(obj) not in [Citation, Hypothesis]:
            raise PermissionDenied(detail=self.message)
        return True


class UpvoteDiscussionComment(RuleBasedPermission):
    message = "Not enough reputation to upvote comment."

    def satisfies_rule(self, request):
        return request.user.reputation >= 1 and not request.user.is_suspended


class UpvoteDiscussionReply(RuleBasedPermission):
    message = "Not enough reputation to upvote reply."

    def satisfies_rule(self, request):
        return request.user.reputation >= 1 and not request.user.is_suspended


class UpvoteDiscussionThread(RuleBasedPermission):
    message = "Not enough reputation to upvote thread."

    def satisfies_rule(self, request):
        return request.user.reputation >= 1 and not request.user.is_suspended


class DownvoteDiscussionComment(RuleBasedPermission):
    message = "Not enough reputation to upvote comment."

    def satisfies_rule(self, request):
        return request.user.reputation >= 25 and not request.user.is_suspended


class DownvoteDiscussionReply(RuleBasedPermission):
    message = "Not enough reputation to upvote reply."

    def satisfies_rule(self, request):
        return request.user.reputation >= 25 and not request.user.is_suspended


class DownvoteDiscussionThread(RuleBasedPermission):
    message = "Not enough reputation to upvote thread."

    def satisfies_rule(self, request):
        return request.user.reputation >= 25 and not request.user.is_suspended


class Endorse(AuthorizationBasedPermission):
    def is_authorized(self, request, view, obj):
        paper_id = get_document_id_from_path(request)
        paper = Paper.objects.get(pk=paper_id)
        author = Author.objects.get(user=request.user)
        return (author in paper.authors.all()) or (
            request.user in paper.moderators.all()
        )


class IsOriginalQuestionPoster(AuthorizationBasedPermission):
    message = "Unable to find target Question post or mismatching OP"

    def is_authorized(self, request, view, obj):
        requestor = request.user
        document_id = get_document_id_from_path(request)
        try:
            target_post_question = ResearchhubPost.objects.get(id=document_id)
            # intentionally checking id since object references may differ
            return target_post_question.created_by.id == requestor.id
        except Exception as e:
            return False
