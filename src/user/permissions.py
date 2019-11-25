from utils.http import RequestMethods
from utils.permissions import AuthorizationBasedPermission


class UpdateAuthor(AuthorizationBasedPermission):
    message = 'Action not permitted.'

    def is_authorized(self, request, view, obj):
        if (request.method == RequestMethods.PUT) or (
            request.method == RequestMethods.PATCH
        ) or (request.method == RequestMethods.DELETE):
            return request.user == obj.user
        return True
