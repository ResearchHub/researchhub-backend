from utils.http import RequestMethods
from utils.permissions import AuthorizationBasedPermission, RuleBasedPermission


class CreatePaper(RuleBasedPermission):
    message = 'Not enough reputation to upload paper.'

    def satisfies_rule(self, request):
        return request.user.reputation >= 1


class UpdatePaper(AuthorizationBasedPermission):
    message = 'Action not permitted.'

    def is_authorized(self, request, view, obj):
        if (
            (request.method == RequestMethods.PATCH)
            or (request.method == RequestMethods.PUT)
        ):
            return (
                (request.user == obj.created_by)
                or (request.user.id in obj.authors)
                or (request.user.id in obj.moderators)
            )
        return True


class FlagPaper(RuleBasedPermission):
    message = 'Not enough reputation to flag paper.'

    def satisfies_rule(self, request):
        if request.method == RequestMethods.DELETE:
            return True
        return request.user.reputation >= 50


class UpvotePaper(RuleBasedPermission):
    message = 'Not enough reputation to upvote paper.'

    def satisfies_rule(self, request):
        return request.user.reputation >= 1


class DownvotePaper(RuleBasedPermission):
    message = 'Not enough reputation to upvote paper.'

    def satisfies_rule(self, request):
        return request.user.reputation >= 25


# TODO: Implement assign moderator functionality
class AssignModerator(AuthorizationBasedPermission):

    def is_authorized(self, request):
        # user is author
        pass
