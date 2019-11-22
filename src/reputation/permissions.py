from utils.http import RequestMethods
from utils.permissions import AuthorizationBasedPermission


class UpdateOrDeleteWithdrawal(AuthorizationBasedPermission):
    message = 'Action not permitted.'

    def is_authorized(self, request, view, obj):
        method = request.method
        user = request.user
        if (
            (method == RequestMethods.PUT)
            or (method == RequestMethods.PATCH)
            or (method == RequestMethods.DELETE)
        ):
            return user == obj.user
        return True
