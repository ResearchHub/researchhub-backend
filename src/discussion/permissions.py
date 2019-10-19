from utils.permissions import AuthorizationBasedPermission, RuleBasedPermission


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


# TODO: Build in endorsement functionality

class Endorse(RuleBasedPermission):

    def satisfies_rule(self, request):
        # user is author or moderator
        pass
