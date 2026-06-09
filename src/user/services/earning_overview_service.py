"""Service for earner dashboard earning overview metrics."""

from user.models import User
from user.services.funding_activity_aggregation import (
    FundingActivityAggregationService,
)


class EarningOverviewService:
    """Aggregate precomputed recipient earnings for a user."""

    def get_earning_overview(self, user: User) -> dict:
        """Return total_earned and by_source breakdown for the given user."""
        return FundingActivityAggregationService.aggregate_earnings_for_user(user.id)
