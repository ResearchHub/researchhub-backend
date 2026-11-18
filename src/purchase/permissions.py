from rest_framework.permissions import SAFE_METHODS, BasePermission

from purchase.services.tip_service import TipService


class CanTipOrReadOnly(BasePermission):
    """Reads are open to the caller; only an account allowed to tip may write."""

    message = TipService.RESTRICTED_MESSAGE

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return TipService().can_tip(request.user)
