from django.db.models import Q

from paper.related_models.paper_submission_model import PaperSubmission
from user.models import Author
from utils.http import POST
from utils.permissions import AuthorizationBasedPermission, RuleBasedPermission


class CreatePaper(RuleBasedPermission):
    message = "Not enough reputation to upload paper."

    def satisfies_rule(self, request):
        return request.user.reputation >= 1 and not request.user.is_suspended


class UpdatePaper(RuleBasedPermission):
    message = "Not enough reputation to upload paper."

    def satisfies_rule(self, request):
        return request.user.reputation >= 1 and not request.user.is_suspended


class IsAuthor(AuthorizationBasedPermission):
    message = "User is not authorized."

    def is_authorized(self, request, view, obj):
        author = Author.objects.get(user=request.user)
        return author in obj.authorship_authors.all()
