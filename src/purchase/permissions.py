from utils.http import RequestMethods
from utils.permissions import AuthorizationBasedPermission

class CanSendRSC(AuthorizationBasedPermission):
    message = 'User cannot send RSC.'

    def has_permission(self, request, view):
        return Gatekeeper.objects.filter(user=request.user).exists()

    def is_authorized(self, request, view, obj):
        return Gatekeeper.objects.filter(user=request.user).exists()
