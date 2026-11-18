from rest_framework.exceptions import PermissionDenied

from user.related_models.user_model import FOUNDATION_EMAIL, User


class TipService:
    """
    Rules for RSC tips (stored as `Purchase.BOOST`, also called "support").

    Tipping is a legacy feature. Its one remaining use is the ResearchHub
    Foundation account rewarding authors for their peer reviews, so no other
    account may tip.
    """

    RESTRICTED_MESSAGE = "Tipping is limited to the ResearchHub Foundation account."

    def can_tip(self, user) -> bool:
        """Whether `user` is the ResearchHub Foundation account."""
        if user is None or not user.is_authenticated:
            return False

        # `User.is_rh_community_account` resolves the account through
        # `get_community_account`, which falls back to a default account when
        # no Foundation user exists. Requiring the Foundation email as well
        # keeps this rule closed in that case instead of moving the privilege
        # to whichever account the fallback returns.
        if user.email != FOUNDATION_EMAIL:
            return False

        return User.is_rh_community_account(user)

    def ensure_can_tip(self, user) -> None:
        """Raise `PermissionDenied` unless `user` may tip."""
        if not self.can_tip(user):
            raise PermissionDenied(self.RESTRICTED_MESSAGE)
