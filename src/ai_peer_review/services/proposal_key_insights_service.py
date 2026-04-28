import logging
import time
from typing import Any, Sequence

from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from ai_peer_review.models import (
    KeyInsightItemType,
    ProposalKeyInsight,
    ProposalKeyInsightItem,
    ProposalReview,
    ReviewStatus,
)
from ai_peer_review.prompts.proposal_review_prompts import (
    build_proposal_key_insights_user_prompt,
    get_proposal_key_insights_system_prompt,
)
from ai_peer_review.services.bedrock_llm_service import BedrockLLMService
from ai_peer_review.services.proposal_review_comment_service import (
    get_ai_expert_user,
    get_proposal_review_ai_expert_comment,
)
from ai_peer_review.services.proposal_review_scoring import parse_json_response
from ai_peer_review.services.proposal_review_service import (
    get_grant_context_text,
    get_proposal_markdown,
)
from researchhub_comment.constants.rh_comment_thread_types import COMMUNITY_REVIEW
from researchhub_comment.models import RhCommentModel
from researchhub_document.models import ResearchhubUnifiedDocument

logger = logging.getLogger(__name__)

_MAX_HUMAN_REVIEWS_TOTAL = 30000
_MAX_LLM_TOKENS = 4096


def _get_ai_peer_review_comment_plain_text(review: ProposalReview) -> str:
    """
    Body text of the platform AI review comment (TIPTAP as plain text), if the
    upserted comment row exists.
    """
    c = get_proposal_review_ai_expert_comment(review)
    if c is None:
        return ""
    return (c.plain_text or "").strip()


def _get_rhf_endorsed_human_reviews(
    unified_document: ResearchhubUnifiedDocument,
) -> str:
    """
    Top-level community reviews on the proposal post whose Review row is
    marked assessed. Excludes the AI review user since
    the AI review is provided separately as ai_review_summary.
    """
    post = unified_document.posts.first()
    if not post:
        return ""

    post_ct = ContentType.objects.get_for_model(post)
    ai_user = get_ai_expert_user()

    qs = RhCommentModel.objects.filter(
        thread__content_type=post_ct,
        thread__object_id=post.id,
        comment_type=COMMUNITY_REVIEW,
        parent__isnull=True,
        is_removed=False,
        reviews__is_assessed=True,
    )
    if ai_user is not None:
        qs = qs.exclude(created_by=ai_user)
    qs = qs.distinct().order_by("created_date", "id")

    blocks: list[str] = []
    for idx, comment in enumerate(qs, start=1):
        rev = comment.reviews.first()
        if rev is not None and rev.score is not None:
            header = f"Reviewer {idx} (score {rev.score:g}/5):"
        else:
            header = f"Reviewer {idx}:"

        body = (comment.plain_text or "").strip()

        blocks.append(f"{header}\n{body}")

    out = "\n\n".join(blocks).strip()
    if len(out) > _MAX_HUMAN_REVIEWS_TOTAL:
        return out[:_MAX_HUMAN_REVIEWS_TOTAL] + "\n[TRUNCATED FOR LENGTH]"
    return out


def _row_list(raw: object, limit: int = 5) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if not isinstance(raw, list):
        return out
    for row in raw[:limit]:
        if not isinstance(row, dict):
            continue
        label = (row.get("label") or "").strip()
        desc = (row.get("description") or "").strip()
        if not label:
            continue
        out.append({"label": label, "description": desc})
    return out


def _parse_strengths_weaknesses(
    data: dict[str, Any],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    return _row_list(data.get("strengths")), _row_list(data.get("weaknesses"))


def _build_items(
    key_insight: ProposalKeyInsight,
    strengths: Sequence[dict[str, str]],
    weaknesses: Sequence[dict[str, str]],
) -> list[ProposalKeyInsightItem]:
    out: list[ProposalKeyInsightItem] = []
    for i, row in enumerate(strengths):
        out.append(
            ProposalKeyInsightItem(
                key_insight=key_insight,
                item_type=KeyInsightItemType.STRENGTH,
                label=row.get("label") or "",
                description=row.get("description") or "",
                order=i,
            )
        )
    for i, row in enumerate(weaknesses):
        out.append(
            ProposalKeyInsightItem(
                key_insight=key_insight,
                item_type=KeyInsightItemType.WEAKNESS,
                label=row.get("label") or "",
                description=row.get("description") or "",
                order=i,
            )
        )
    return out


def run_proposal_key_insights(
    review_id: int, *, force: bool = False
) -> ProposalKeyInsight:
    """
    Run the key-insights Bedrock pass for a completed ``ProposalReview`` and
    persist ``ProposalKeyInsight`` + child items.
    """
    review = ProposalReview.objects.select_related("unified_document", "grant").get(
        pk=review_id
    )
    if review.status != ReviewStatus.COMPLETED:
        raise ValueError(
            f"Proposal review {review_id} must be completed (status={review.status!r})."
        )

    key_insight, _created = ProposalKeyInsight.objects.get_or_create(
        proposal_review=review,
    )
    if key_insight.status == ReviewStatus.COMPLETED and not force:
        return key_insight

    key_insight.status = ReviewStatus.PROCESSING
    key_insight.error_message = ""
    key_insight.save(update_fields=["status", "error_message", "updated_date"])

    t0 = time.monotonic()
    llm = BedrockLLMService()

    try:
        proposal_text = get_proposal_markdown(review.unified_document)
        rfp_context = None
        if review.grant_id and review.grant is not None:
            rfp_context = get_grant_context_text(review.grant)
        ai_summary = _get_ai_peer_review_comment_plain_text(review)
        human = _get_rhf_endorsed_human_reviews(review.unified_document)
        system = get_proposal_key_insights_system_prompt()
        user = build_proposal_key_insights_user_prompt(
            proposal_text,
            rfp_context=rfp_context,
            ai_review_summary=ai_summary,
            human_reviews_text=human,
        )
        raw = llm.invoke(
            system,
            user,
            max_tokens=_MAX_LLM_TOKENS,
            temperature=0.0,
        )
        data = parse_json_response(raw)
        if not isinstance(data, dict):
            raise ValueError("Key insights response JSON must be an object")
        tldr = (data.get("tldr") or "").strip()
        strengths, weaknesses = _parse_strengths_weaknesses(data)
        elapsed = time.monotonic() - t0

        with transaction.atomic():
            key_insight.tldr = tldr
            key_insight.llm_model = llm.model_id
            key_insight.processing_time = elapsed
            key_insight.status = ReviewStatus.COMPLETED
            key_insight.error_message = ""
            key_insight.save(
                update_fields=[
                    "tldr",
                    "llm_model",
                    "processing_time",
                    "status",
                    "error_message",
                    "updated_date",
                ]
            )
            key_insight.items.all().delete()
            items = _build_items(key_insight, strengths, weaknesses)
            if items:
                ProposalKeyInsightItem.objects.bulk_create(items)

    except Exception as e:
        logger.exception("Proposal key insights failed for review %s", review_id)
        key_insight.status = ReviewStatus.FAILED
        key_insight.error_message = str(e)[:4000]
        if key_insight.processing_time is None:
            key_insight.processing_time = time.monotonic() - t0
        key_insight.save(
            update_fields=["status", "error_message", "processing_time", "updated_date"]
        )

    return key_insight
