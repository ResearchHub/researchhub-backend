from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from django.utils import timezone

from researchhub_comment.constants.rh_comment_thread_types import COMMUNITY_REVIEW
from researchhub_comment.models import RhCommentModel
from user.models import User

REVIEW_COOLDOWN_DAYS = 4


@dataclass
class ReviewAvailability:
    can_review: bool
    available_at: Optional[datetime] = None


def get_review_availability(user: User) -> ReviewAvailability:
    """Check if user can create a review now, or when they'll be able to."""
    latest_review = (
        RhCommentModel.objects.filter(
            created_by=user,
            comment_type=COMMUNITY_REVIEW,
        )
        .order_by("-created_date")
        .first()
    )
    if not latest_review:
        return ReviewAvailability(can_review=True)

    next_available = latest_review.created_date + timedelta(days=REVIEW_COOLDOWN_DAYS)
    if next_available <= timezone.now():
        return ReviewAvailability(can_review=True)

    return ReviewAvailability(can_review=False, available_at=next_available)

