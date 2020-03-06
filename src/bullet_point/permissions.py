from utils.http import POST, PATCH, PUT, DELETE
from utils.permissions import AuthorizationBasedPermission, RuleBasedPermission


class CreateBulletPoint(RuleBasedPermission):
    message = 'Not enough reputation to create bullet point.'

    def satisfies_rule(self, request):
        if request.method == POST:
            return request.user.reputation >= 1
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
