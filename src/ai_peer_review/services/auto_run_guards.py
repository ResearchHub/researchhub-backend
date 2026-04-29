from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone

from ai_peer_review.constants import (
    AUTO_KI_DAILY_CAP_PER_REVIEW_DEFAULT,
    AUTO_PR_DAILY_CAP_PER_GRANT_DEFAULT,
)
from ai_peer_review.models import ProposalReview, ReviewStatus
from researchhub_comment.constants.rh_comment_thread_types import COMMUNITY_REVIEW
from researchhub_comment.models import RhCommentModel
from researchhub_document.models import ResearchhubUnifiedDocument


def _setting(name: str, default: int) -> int:
    return int(getattr(settings, name, default))


def _today_key_part() -> str:
    return timezone.now().strftime("%Y%m%d")


def _incr_daily_count(cache_key: str, ttl_seconds: int = 86400) -> int:
    try:
        return cache.incr(cache_key)
    except ValueError:
        cache.add(cache_key, 1, ttl_seconds)
        return 1


def _decr_daily_count(cache_key: str) -> None:
    try:
        cache.decr(cache_key)
    except ValueError:
        pass


def has_assessed_comment_on_proposal_post(
    unified_document: ResearchhubUnifiedDocument,
) -> bool:
    """True if any top-level community comment on the proposal post has an assessed Review."""
    post = unified_document.posts.first()
    if not post:
        return False
    post_ct = ContentType.objects.get_for_model(post)
    return RhCommentModel.objects.filter(
        thread__content_type=post_ct,
        thread__object_id=post.id,
        comment_type=COMMUNITY_REVIEW,
        parent__isnull=True,
        is_removed=False,
        reviews__is_assessed=True,
    ).exists()


def should_skip_proposal_review(
    review: ProposalReview,
    *,
    force: bool = False,
) -> tuple[bool, str]:
    """
    Auto-run proposal review guards.

    * Always skip if no grant (management / product rule).
    * Skip if a run is already in flight (PROCESSING).
    * Unless ``force``: per-grant daily cap.
    """
    if review.grant_id is None:
        return True, "no_grant"

    if review.status == ReviewStatus.PROCESSING:
        return True, "processing"

    if force:
        return False, ""

    cap = _setting("AUTO_PR_DAILY_CAP_PER_GRANT", AUTO_PR_DAILY_CAP_PER_GRANT_DEFAULT)
    day = _today_key_part()
    cap_key = f"ai_peer_review:auto:pr:cap:{review.grant_id}:{day}"
    count = _incr_daily_count(cap_key)
    if count > cap:
        _decr_daily_count(cap_key)
        return True, "daily_cap"

    return False, ""


def should_skip_key_insights(
    review: ProposalReview,
    *,
    force: bool = False,
) -> tuple[bool, str]:
    """
    Auto-run key insights guards.

    * Requires completed proposal review.
    * Skip if key insight row is already processing.
    * Unless ``force``: require at least one assessed comment on the proposal post
      and per-review daily cap.
    """
    if review.status != ReviewStatus.COMPLETED:
        return True, "proposal_review_not_completed"

    try:
        ki = review.key_insight
    except ObjectDoesNotExist:
        ki = None
    if ki is not None and ki.status == ReviewStatus.PROCESSING:
        return True, "key_insight_processing"

    if force:
        return False, ""

    ud = review.unified_document
    if not has_assessed_comment_on_proposal_post(ud):
        return True, "no_assessed_comments"

    cap = _setting("AUTO_KI_DAILY_CAP_PER_REVIEW", AUTO_KI_DAILY_CAP_PER_REVIEW_DEFAULT)
    day = _today_key_part()
    cap_key = f"ai_peer_review:auto:ki:cap:{review.id}:{day}"
    count = _incr_daily_count(cap_key)
    if count > cap:
        _decr_daily_count(cap_key)
        return True, "daily_cap"

    return False, ""
