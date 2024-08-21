from django.db.models import Q

from paper.related_models.paper_submission_model import PaperSubmission
from user.models import Author
from utils.http import POST, RequestMethods
from utils.permissions import AuthorizationBasedPermission, RuleBasedPermission


class CreatePaper(RuleBasedPermission):
    message = "Not enough reputation to upload paper."

    def satisfies_rule(self, request):
        return request.user.reputation >= 1 and not request.user.is_suspended


class UpdatePaper(RuleBasedPermission):
    message = "Not enough reputation to upload paper."

    def satisfies_rule(self, request):
        return request.user.reputation >= 1 and not request.user.is_suspended


class FlagPaper(RuleBasedPermission):
    message = "Not enough reputation to flag paper."

    def satisfies_rule(self, request):
        if request.method == RequestMethods.DELETE:
            return True
        return request.user.reputation >= 1


class UpvotePaper(RuleBasedPermission):
    message = "Not enough reputation to upvote paper."

    def satisfies_rule(self, request):
        return request.user.reputation >= 1 and not request.user.is_suspended


class DownvotePaper(RuleBasedPermission):
    message = "Not enough reputation to upvote paper."

    def satisfies_rule(self, request):
        return request.user.reputation >= 25 and not request.user.is_suspended


class IsAuthor(AuthorizationBasedPermission):
    message = "User is not authorized."

    def is_authorized(self, request, view, obj):
        author = Author.objects.get(user=request.user)
        return author in obj.authors.all()


class UpdateOrDeleteAdditionalFile(AuthorizationBasedPermission):
    message = "User is not authorized."

    def is_authorized(self, request, view, obj):
        if request.method == POST:
            return True

        if request.user.moderator:
            return True
        elif obj.created_by == request.user:
            return True
        else:
            author = Author.objects.get(user=request.user)
            return author in obj.paper.authors.all()


class IsAllowedToUpdateAsyncPaper(AuthorizationBasedPermission):
    def is_authorized(self, request, view, obj):
        if request.method != POST:
            return False

        submission_id = request.data.get("submission_id", None)
        if submission_id is not None:
            return PaperSubmission.objects.filter(
                ~Q(paper_status=PaperSubmission.COMPLETE),
                id=submission_id,
                uploaded_by=request.user,
            ).exists()

        return False
