from utils.permissions import RuleBasedPermission


class CreateHub(RuleBasedPermission):
    message = 'Not enough reputation to create hub.'

    def satisfies_rule(self, request):
        return request.user.reputation >= 100
