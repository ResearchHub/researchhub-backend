from utils.permissions import (
    AuthorizationBasedPermission,
    RuleBasedPermission,
)

class CreateReview(RuleBasedPermission):
    message = 'Not allowed to create a review'

    def satisfies_rule(self, request):
        return True

class UpdateReview(AuthorizationBasedPermission):
    message = 'Action not permitted.'

    def is_authorized(self, request, view, obj):
        print('obj', obj.__dict__)
        return obj.created_by == request.user