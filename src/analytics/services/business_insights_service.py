from datetime import UTC, datetime
from decimal import Decimal

from analytics.services.insights.endowment import get_endowment_metrics
from analytics.services.insights.expert_finder import get_expert_finder_metrics
from analytics.services.insights.funding import get_funding_metrics
from analytics.services.insights.pages import get_page_metrics
from analytics.services.insights.peer_reviews import get_peer_review_metrics
from analytics.services.insights.users import get_user_metrics
from analytics.services.insights.wac import get_contributor_metrics


def _is_numeric(value) -> bool:
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)


def merge_previous_values(current, previous):
    """Attach ``*_previous`` siblings for every comparable numeric leaf."""
    if not isinstance(current, dict):
        return current

    previous = previous if isinstance(previous, dict) else {}
    merged = {}
    for key, value in current.items():
        if isinstance(value, dict):
            merged[key] = merge_previous_values(value, previous.get(key, {}))
        elif isinstance(value, list):
            merged[key] = value
        elif _is_numeric(value):
            merged[key] = value
            merged[f"{key}_previous"] = previous.get(key, 0)
        else:
            merged[key] = value
    return merged


class BusinessInsightsService:
    def __init__(self, report_period):
        self.period = report_period

    def build(self):
        previous_period = self.period.previous()
        current_metrics = self._build_metrics(self.period)
        previous_metrics = self._build_metrics(previous_period)
        return {
            "generated_at": datetime.now(UTC),
            "period": {
                **self.period.as_dict(),
                "previous_start": previous_period.start,
                "previous_end": previous_period.end,
            },
            **merge_previous_values(current_metrics, previous_metrics),
        }

    def _build_metrics(self, period):
        contributors = get_contributor_metrics(period)
        users = get_user_metrics(period)
        return {
            "funding": get_funding_metrics(period),
            "users": {
                "weekly_active_contributors": contributors["wac"]["count"],
                "verified_weekly_active_contributors": contributors["verified_wac"][
                    "count"
                ],
                **users,
            },
            "pages": get_page_metrics(period),
            "peer_reviews": get_peer_review_metrics(period),
            "endowment": get_endowment_metrics(period),
            "expert_finder": get_expert_finder_metrics(period),
        }
