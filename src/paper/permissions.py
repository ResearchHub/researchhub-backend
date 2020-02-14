from user.models import Author
from utils.http import RequestMethods
from utils.permissions import AuthorizationBasedPermission, RuleBasedPermission


class CreatePaper(RuleBasedPermission):
    message = 'Not enough reputation to upload paper.'

    def satisfies_rule(self, request):
        return request.user.reputation >= 1


class UpdatePaper(RuleBasedPermission):
    message = 'Not enough reputation to upload paper.'

    def satisfies_rule(self, request):
        return request.user.reputation >= 1


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

class IsModeratorOrVerifiedAuthor(AuthorizationBasedPermission):
    message = 'User is not authorized.'

    def is_authorized(self, request, view, obj):
        if request.user.moderator:
            return True
        else:
            author = Author.objects.get(user=request.user)
            return author in obj.authors.all()

class IsAuthor(AuthorizationBasedPermission):
    message = 'User is not authorized.'

    def is_authorized(self, request, view, obj):
        author = Author.objects.get(user=request.user)
        return author in obj.authors.all()
