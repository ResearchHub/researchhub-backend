from utils.permissions import RuleBasedPermission


class IsModerator(RuleBasedPermission):
    message = 'User is not authorized'

    def satisfies_rule(self, request):
        return request.user.moderator
