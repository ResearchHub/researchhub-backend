from utils.http import RequestMethods
from utils.permissions import AuthorizationBasedPermission
from user.related_models.gatekeeper_model import Gatekeeper

class CanSendRSC(AuthorizationBasedPermission):
    message = 'User cannot send RSC.'

    def has_permission(self, request, view):
        return Gatekeeper.objects.filter(user=request.user, type="SEND_RSC").exists()

    def is_authorized(self, request, view, obj):
        return Gatekeeper.objects.filter(user=request.user, type="SEND_RSC").exists()
