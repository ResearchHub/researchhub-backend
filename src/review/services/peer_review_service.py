from datetime import datetime, timedelta
from typing import Optional

from django.utils import timezone

from researchhub_comment.constants.rh_comment_thread_types import COMMUNITY_REVIEW
from researchhub_comment.models import RhCommentModel
from user.models import User

REVIEW_COOLDOWN_DAYS = 4


def get_next_available_review_time(user: User) -> Optional[datetime]:
    """Returns when user can next create a review, or None if available now."""
    latest_review = (
        RhCommentModel.objects.filter(
            created_by=user,
            comment_type=COMMUNITY_REVIEW,
        )
        .order_by("-created_date")
        .first()
    )
    if not latest_review:
        return None
    next_available = latest_review.created_date + timedelta(days=REVIEW_COOLDOWN_DAYS)
    if next_available <= timezone.now():
        return None
    return next_available

