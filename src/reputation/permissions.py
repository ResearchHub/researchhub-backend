from rest_framework.permissions import BasePermission, SAFE_METHODS


class RuleBasedPermission(BasePermission):
    class Meta:
        abstract = True

    def has_permission(self, request, view):
        if self.is_read_only_request(request):
            return True
        return self.satisfies_rule(request)

    def is_read_only_request(self, request):
        return request.method in SAFE_METHODS

    def satisfies_rule(self, request):
        raise NotImplementedError


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


class CreateHub(RuleBasedPermission):
    message = 'Not enough reputation to create hub.'

    def satisfies_rule(self, request):
        return request.user.reputation >= 100


class CreatePaper(RuleBasedPermission):
    message = 'Not enough reputation to upload paper.'

    def satisfies_rule(self, request):
        return request.user.reputation >= 1


class CreateSummary(RuleBasedPermission):
    message = 'Not enough reputation to create summary.'

    def satisfies_rule(self, request):
        return request.user.reputation >= 5


class UpdateDiscussionComment(RuleBasedPermission):
    message = 'Action not permitted.'

    def satisfies_rule(self, request):
        # user must be object creator
        pass


class UpdateDiscussionReply(RuleBasedPermission):
    message = 'Action not permitted.'

    def satisfies_rule(self, request):
        # user must be object creator
        pass


class UpdateDiscussionThread(RuleBasedPermission):
    message = 'Action not permitted.'

    def satisfies_rule(self, request):
        # user must be object creator
        pass


class UpdatePaper(RuleBasedPermission):
    message = 'Action not permitted.'

    def satisfies_rule(self, request):
        # user is author, moderator, or creator
        pass


class UpdateSummary(RuleBasedPermission):
    message = 'Not enough reputation to update summary.'

    def satisfies_rule(self, request):
        return request.user.reputation >= 50


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


class FlagPaper(RuleBasedPermission):
    message = 'Not enough reputation to flag paper.'

    def satisfies_rule(self, request):
        return request.user.reputation >= 50


class FlagSummary(RuleBasedPermission):
    message = 'Not enough reputation to flag summary.'

    def satisfies_rule(self, request):
        return request.user.reputation >= 50


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


class UpvotePaper(RuleBasedPermission):
    message = 'Not enough reputation to upvote paper.'

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


class DownvotePaper(RuleBasedPermission):
    message = 'Not enough reputation to upvote paper.'

    def satisfies_rule(self, request):
        return request.user.reputation >= 25


# Misc

class ApproveSummary(RuleBasedPermission):
    message = 'Not enough reputation to approve summary.'

    def satisfies_rule(self, request):
        return request.user.reputation >= 50


class RejectSummary(RuleBasedPermission):
    message = 'Not enough reputation to reject summary.'

    def satisfies_rule(self, request):
        return request.user.reputation >= 50


class AssignModerator(RuleBasedPermission):

    def satisfies_rule(self, request):
        # user is author
        pass


class Endorse(RuleBasedPermission):

    def satisfies_rule(self, request):
        # user is author or moderator
        pass
