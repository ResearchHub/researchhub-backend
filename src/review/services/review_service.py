from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from django.utils import timezone

from researchhub_comment.constants.rh_comment_thread_types import COMMUNITY_REVIEW
from researchhub_comment.models import RhCommentModel
from user.models import User

REVIEW_WINDOW_DAYS = 7
MAX_REVIEWS_PER_WINDOW = 2


@dataclass
class ReviewAvailability:
    can_review: bool
    available_at: Optional[datetime] = None


def get_review_availability(user: User) -> ReviewAvailability:
    """Check if user can create a review now, or when they'll be able to."""
    window_duration = timedelta(days=REVIEW_WINDOW_DAYS)
    window_start = timezone.now() - window_duration

    base_query = RhCommentModel.objects.filter(
        created_by=user,
        comment_type=COMMUNITY_REVIEW,
        created_date__gte=window_start,
    )

    if base_query.count() < MAX_REVIEWS_PER_WINDOW:
        return ReviewAvailability(can_review=True)

    # User has hit the limit. Find when the oldest review expires from the window.
    oldest_review_date = base_query.order_by("created_date").values_list(
        "created_date", flat=True
    ).first()
    next_available = oldest_review_date + window_duration

    return ReviewAvailability(can_review=False, available_at=next_available)

