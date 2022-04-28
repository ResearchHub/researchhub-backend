from utils.permissions import (
    AuthorizationBasedPermission,
)

class AllowedToUpdateReview(AuthorizationBasedPermission):
    message = 'Action not permitted.'

    def is_authorized(self, request, view, obj):
        return obj.created_by == request.user