from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from purchase.related_models.constants.support import (
    MAXIMUM_DAILY_TIP_TOTAL_RSC,
    MAXIMUM_TIP_AMOUNT_USD,
    TIP_LIMIT_WINDOW_HOURS,
)
from purchase.related_models.purchase_model import Purchase
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from researchhub_comment.constants.rh_comment_thread_types import REVIEW_COMMENT_TYPES
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from user.related_models.user_model import User


class TipService:
    RESTRICTED_MESSAGE = "Tipping is limited to the ResearchHub Foundation account."
    INVALID_TARGET_MESSAGE = "Tips can only be sent on peer reviews."
    AMOUNT_LIMIT_MESSAGE = "Tip exceeds the maximum amount."
    DAILY_LIMIT_MESSAGE = "Tip exceeds the daily limit."

    def can_tip(self, user) -> bool:
        if user is None or not user.is_authenticated:
            return False

        return User.is_rh_community_account(user)

    def ensure_can_tip(self, user) -> None:
        if not self.can_tip(user):
            raise PermissionDenied(self.RESTRICTED_MESSAGE)

    def ensure_tip_allowed(self, user, object_id, amount: Decimal) -> None:
        self._ensure_peer_review(object_id)
        self._ensure_within_limits(user, amount)

    def _ensure_peer_review(self, object_id) -> None:
        try:
            is_peer_review = RhCommentModel.objects.filter(
                id=object_id,
                comment_type__in=REVIEW_COMMENT_TYPES,
            ).exists()
        except TypeError, ValueError:
            is_peer_review = False

        if not is_peer_review:
            raise ValidationError(self.INVALID_TARGET_MESSAGE)

    def _ensure_within_limits(self, user, amount: Decimal) -> None:
        if amount > RscExchangeRate.usd_to_rsc(MAXIMUM_TIP_AMOUNT_USD):
            raise ValidationError(self.AMOUNT_LIMIT_MESSAGE)

        window_start = timezone.now() - timedelta(hours=TIP_LIMIT_WINDOW_HOURS)
        recent_total = (
            Purchase.objects.for_user(user.id)
            .filter(purchase_type=Purchase.BOOST, created_date__gte=window_start)
            .sum()
        )
        if recent_total + amount > MAXIMUM_DAILY_TIP_TOTAL_RSC:
            raise ValidationError(self.DAILY_LIMIT_MESSAGE)
