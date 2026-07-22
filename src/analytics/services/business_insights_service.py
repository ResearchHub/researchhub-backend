from datetime import UTC, datetime

from analytics.services.insights.endowment import get_endowment_metrics
from analytics.services.insights.expert_finder import get_expert_finder_metrics
from analytics.services.insights.funding import get_funding_metrics
from analytics.services.insights.pages import get_page_metrics
from analytics.services.insights.peer_reviews import get_peer_review_metrics
from analytics.services.insights.users import get_user_metrics
from analytics.services.insights.wac import get_contributor_metrics


class BusinessInsightsService:
    def __init__(self, report_period):
        self.period = report_period

    def build(self):
        contributors = get_contributor_metrics(self.period)
        users = get_user_metrics(self.period)
        expert_finder = get_expert_finder_metrics(self.period)
        return {
            "generated_at": datetime.now(UTC),
            "period": self.period.as_dict(),
            "funding": get_funding_metrics(self.period),
            "users": {
                "weekly_active_contributors": contributors["wac"]["count"],
                "verified_weekly_active_contributors": contributors["verified_wac"][
                    "count"
                ],
                **users,
            },
            "pages": get_page_metrics(self.period),
            "peer_reviews": get_peer_review_metrics(self.period),
            "endowment": get_endowment_metrics(self.period),
            "expert_finder": expert_finder,
        }
