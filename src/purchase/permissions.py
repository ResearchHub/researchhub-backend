from rest_framework.permissions import BasePermission

from user.related_models.gatekeeper_model import Gatekeeper
from utils.permissions import AuthorizationBasedPermission


class IsModeratorOrGrantContact(BasePermission):
    message = "Need to be the grant creator, a grant contact, or a moderator."

    def has_permission(self, request, view):
        return request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        if request.user.moderator or obj.created_by_id == request.user.id:
            return True
        return obj.contacts.filter(id=request.user.id).exists()


class CanSendRSC(AuthorizationBasedPermission):
    message = "User cannot send RSC."

    def has_permission(self, request, view):
        return Gatekeeper.objects.filter(user=request.user, type="SEND_RSC").exists()

    def is_authorized(self, request, view, obj):
        return Gatekeeper.objects.filter(user=request.user, type="SEND_RSC").exists()
