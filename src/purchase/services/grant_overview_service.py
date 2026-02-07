from user.models import User


class GrantOverviewService:
    """Service for calculating grant-specific dashboard metrics."""

    def get_grant_overview(self, _user: User, _grant_id: int) -> dict:
        """Return metrics for a specific grant."""
        return {
            "total_raised_usd": 0.0,
            "total_applicants": 0,
            "matched_funding_usd": 0.0,
            "recent_updates": 0,
        }
