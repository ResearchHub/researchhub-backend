from .utils import get_paper_id_from_path
from paper.models import Paper
from user.models import Author
from utils.permissions import (
    AuthorizationBasedPermission,
    RuleBasedPermission,
    PermissionDenied
)


class CreateDiscussionComment(RuleBasedPermission):
    message = 'Not enough reputation to create comment.'

    def satisfies_rule(self, request):
        return request.user.reputation >= 1


class CreateDiscussionReply(RuleBasedPermission):
    message = 'Not enough reputation to create reply.'

    def satisfies_rule(self, request):
        return request.user.reputation >= 1


class CreateDiscussionThread(RuleBasedPermission):
    message = 'Not enough reputation to create thread.'

    def satisfies_rule(self, request):
        return request.user.reputation >= 1


class UpdateDiscussionComment(AuthorizationBasedPermission):
    message = 'Action not permitted.'

    def is_authorized(self, request, view, obj):
        return obj.created_by == request.user


class UpdateDiscussionReply(AuthorizationBasedPermission):
    message = 'Action not permitted.'

    def is_authorized(self, request, view, obj):
        return obj.created_by == request.user


class UpdateDiscussionThread(AuthorizationBasedPermission):
    message = 'Action not permitted.'

    def is_authorized(self, request, view, obj):
        return obj.created_by == request.user


class FlagDiscussionComment(RuleBasedPermission):
    message = 'Not enough reputation to flag comment.'

    def satisfies_rule(self, request):
        return request.user.reputation >= 1


class FlagDiscussionReply(RuleBasedPermission):
    message = 'Not enough reputation to flag reply.'

    def satisfies_rule(self, request):
        return request.user.reputation >= 1


class FlagDiscussionThread(RuleBasedPermission):
    message = 'Not enough reputation to flag thread.'

    def satisfies_rule(self, request):
        return request.user.reputation >= 1


class Vote(AuthorizationBasedPermission):
    message = 'Can not vote on own content'

    def is_authorized(self, request, view, obj):
        if request.user == obj.created_by:
            raise PermissionDenied(detail=self.message)
        return True


class UpvoteDiscussionComment(RuleBasedPermission):
    message = 'Not enough reputation to upvote comment.'

    def satisfies_rule(self, request):
        return request.user.reputation >= 1


class UpvoteDiscussionReply(RuleBasedPermission):
    message = 'Not enough reputation to upvote reply.'

    def satisfies_rule(self, request):
        return request.user.reputation >= 1


class UpvoteDiscussionThread(RuleBasedPermission):
    message = 'Not enough reputation to upvote thread.'

    def satisfies_rule(self, request):
        return request.user.reputation >= 1


class DownvoteDiscussionComment(RuleBasedPermission):
    message = 'Not enough reputation to upvote comment.'

    def satisfies_rule(self, request):
        return request.user.reputation >= 25


class DownvoteDiscussionReply(RuleBasedPermission):
    message = 'Not enough reputation to upvote reply.'

    def satisfies_rule(self, request):
        return request.user.reputation >= 25


class DownvoteDiscussionThread(RuleBasedPermission):
    message = 'Not enough reputation to upvote thread.'

    def satisfies_rule(self, request):
        return request.user.reputation >= 25


class Endorse(AuthorizationBasedPermission):

    def is_authorized(self, request, view, obj):
        paper_id = get_paper_id_from_path(request)
        paper = Paper.objects.get(pk=paper_id)
        author = Author.objects.get(user=request.user)
        return (
            (author in paper.authors.all())
            or (request.user in paper.moderators.all())
        )
