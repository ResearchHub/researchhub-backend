from user.models import User


class DashboardService:
    """Calculates funder dashboard metrics for a given user."""

    def __init__(self, user: User):
        self.user = user

    def get_overview(self) -> dict:
        return {}

    def get_grant_overview(self, grant_id: int) -> dict:
        return {}
