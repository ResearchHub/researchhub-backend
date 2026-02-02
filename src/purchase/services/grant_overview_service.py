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
            "impact": {
                "milestones": {
                    "funding_contributed": {"current": 0.0, "target": 1000.0},
                    "researchers_supported": {"current": 0.0, "target": 1.0},
                    "matched_funding": {"current": 0.0, "target": 1000.0},
                },
                "funding_over_time": [],
                "topic_breakdown": [],
                "update_frequency": [],
                "institutions_supported": [],
            },
        }
