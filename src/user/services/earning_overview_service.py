"""Service for earner dashboard earning overview metrics."""

from user.models import User
from user.services.funding_activity_reporting import FundingActivityReportingService


class EarningOverviewService:
    """Aggregate precomputed recipient earnings for a user."""

    def get_earning_overview(self, user: User) -> dict:
        """Return total_earned and by_source breakdown for the given user."""
        return FundingActivityReportingService.earnings_for_user(user.id)
