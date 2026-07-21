from datetime import timedelta

from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, Q

from purchase.models import Purchase
from reputation.constants.bounty import ASSESSMENT_PERIOD_DAYS
from reputation.models import Bounty, BountySolution
from researchhub_comment.models import RhCommentModel
from researchhub_document.related_models.constants.document_type import (
    PAPER,
    PREREGISTRATION,
)
from review.models import Review
from user.models import User


def _get_assessment_events(period, comment_content_type):
    """Return the first foundation tip/award timestamp per assessed comment."""
    community = User.objects.get_community_account()
    events = {}

    tips = Purchase.objects.filter(
        user=community,
        content_type=comment_content_type,
        created_date__gte=period.start,
        created_date__lt=period.end,
    ).values_list("object_id", "created_date")
    awards = BountySolution.objects.filter(
        status=BountySolution.Status.AWARDED,
        content_type=comment_content_type,
        bounty__created_by=community,
        updated_date__gte=period.start,
        updated_date__lt=period.end,
    ).values_list("object_id", "updated_date")

    for comment_id, event_date in list(tips) + list(awards):
        previous = events.get(comment_id)
        if previous is None or event_date < previous:
            events[comment_id] = event_date

    assessed_comment_ids = set(
        Review.objects.filter(
            is_assessed=True,
            is_removed=False,
            content_type=comment_content_type,
            object_id__in=events,
        ).values_list("object_id", flat=True)
    )
    return {
        comment_id: event_date
        for comment_id, event_date in events.items()
        if comment_id in assessed_comment_ids
    }


def _average_assessment_days(assessment_events, comment_content_type):
    """Average from bounty assessment start through the actual tip/award."""
    if not assessment_events:
        return None

    starts_by_comment = {}
    bounty_solutions = BountySolution.objects.filter(
        content_type=comment_content_type,
        object_id__in=assessment_events,
        bounty__bounty_type=Bounty.Type.REVIEW,
        bounty__parent__isnull=True,
        bounty__assessment_end_date__isnull=False,
    ).values_list("object_id", "bounty__assessment_end_date")

    for comment_id, assessment_end_date in bounty_solutions:
        assessment_start = assessment_end_date - timedelta(
            days=ASSESSMENT_PERIOD_DAYS
        )
        event_date = assessment_events[comment_id]
        if assessment_start > event_date:
            continue
        previous = starts_by_comment.get(comment_id)
        if previous is None or assessment_start > previous:
            starts_by_comment[comment_id] = assessment_start

    durations = [
        (assessment_events[comment_id] - assessment_start).total_seconds() / 86400
        for comment_id, assessment_start in starts_by_comment.items()
    ]
    return round(sum(durations) / len(durations), 2) if durations else None


def get_peer_review_metrics(period):
    reviews = RhCommentModel.objects.filter(
        comment_type="REVIEW",
        is_removed=False,
        created_date__gte=period.start,
        created_date__lt=period.end,
    )
    counts = reviews.aggregate(
        submitted_reviews=Count("id", distinct=True),
        on_preprints=Count(
            "id",
            filter=Q(reviews__unified_document__document_type=PAPER),
            distinct=True,
        ),
        on_proposals=Count(
            "id",
            filter=Q(reviews__unified_document__document_type=PREREGISTRATION),
            distinct=True,
        ),
    )
    comment_content_type = ContentType.objects.get_for_model(RhCommentModel)
    assessment_events = _get_assessment_events(period, comment_content_type)
    counts["assessed_reviews"] = len(assessment_events)
    counts["avg_review_assessment_days"] = _average_assessment_days(
        assessment_events,
        comment_content_type,
    )
    return counts
