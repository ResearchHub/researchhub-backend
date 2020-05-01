from utils.permissions import AuthorizationBasedPermission, RuleBasedPermission


class CreateHub(RuleBasedPermission):
    message = 'Not enough reputation to create hub.'

    def satisfies_rule(self, request):
        return request.user.reputation >= 100


class IsSubscribed(AuthorizationBasedPermission):
    message = 'Must be subscribed.'

    def is_authorized(self, request, view, obj):
        return request.user in obj.subscribers.all()


class IsNotSubscribed(AuthorizationBasedPermission):
    message = 'Must not be subscribed.'

    def is_authorized(self, request, view, obj):
        return request.user not in obj.subscribers.all()
