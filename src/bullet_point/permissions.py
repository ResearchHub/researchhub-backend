from paper.models import Paper
from researchhub.lib import get_paper_id_from_path
from user.models import Author
from utils.http import POST, PATCH, PUT, DELETE
from utils.permissions import AuthorizationBasedPermission, RuleBasedPermission


class CreateBulletPoint(RuleBasedPermission):
    message = 'Not enough reputation to create bullet point.'

    def satisfies_rule(self, request):
        if request.method == POST:
            return request.user.reputation >= 1 and not request.user.is_suspended and not request.user.probable_spammer
        return True


class UpdateOrDeleteBulletPoint(AuthorizationBasedPermission):
    message = 'You do not have permission to perform this action.'

    def is_authorized(self, request, view, obj):
        method = request.method
        user = request.user
        if method == PATCH:
            return (
                (user == obj.created_by)
                or check_user_is_moderator(user, obj)
            )
        if method == PUT:
            return False
        if method == DELETE:
            return user.is_staff
        return True


def check_user_is_moderator(user, bullet_point):
    moderators = bullet_point.paper.moderators.all()
    return user in moderators


class Censor(AuthorizationBasedPermission):
    message = 'Need to be a moderator to delete bullet point.'

    def is_authorized(self, request, view, obj):
        return request.user.moderator


class Endorse(AuthorizationBasedPermission):
    message = 'Not authorized to endorse bullet point.'

    def is_authorized(self, request, view, obj):
        paper_id = get_paper_id_from_path(request)
        paper = Paper.objects.get(pk=paper_id)
        author = Author.objects.get(user=request.user)
        return author in paper.authors.all()


class Flag(RuleBasedPermission):
    message = 'Not enough reputation to flag bullet point.'

    def satisfies_rule(self, request):
        return request.user.reputation >= 1
