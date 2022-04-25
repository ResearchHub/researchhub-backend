from utils.permissions import (
    AuthorizationBasedPermission,
    RuleBasedPermission,
)

class AllowedToCreateReview(RuleBasedPermission):
    message = 'Not allowed to create a review'

    def satisfies_rule(self, request):
        return True

class AllowedToUpdateReview(AuthorizationBasedPermission):
    message = 'Action not permitted.'

    def is_authorized(self, request, view, obj):
        return obj.created_by == request.user