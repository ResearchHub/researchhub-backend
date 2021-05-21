from utils.permissions import RuleBasedPermission


class IsModerator(RuleBasedPermission):
    message = 'User is not authorized'

    def satisfies_rule(self, request):
        if request.user.moderator:
            return True
        return False
