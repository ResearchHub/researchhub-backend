from rest_framework.exceptions import PermissionDenied

from user.related_models.user_model import FOUNDATION_EMAIL, User


class TipService:
    RESTRICTED_MESSAGE = "Tipping is limited to the ResearchHub Foundation account."

    def can_tip(self, user) -> bool:
        if user is None or not user.is_authenticated:
            return False

        if user.email != FOUNDATION_EMAIL:
            return False

        return User.is_rh_community_account(user)

    def ensure_can_tip(self, user) -> None:
        if not self.can_tip(user):
            raise PermissionDenied(self.RESTRICTED_MESSAGE)
