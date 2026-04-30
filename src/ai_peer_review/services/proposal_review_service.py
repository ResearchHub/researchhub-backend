import logging
import time

from ai_peer_review.constants import PROPOSAL_REVIEW_MAX_OUTPUT_TOKENS
from ai_peer_review.models import OverallConfidence, ProposalReview, Status
from ai_peer_review.prompts.proposal_review_prompts import (
    build_proposal_review_user_prompt,
    get_proposal_review_system_prompt,
)
from ai_peer_review.services.author_context import build_author_context_snippet
from ai_peer_review.services.bedrock_llm_service import BedrockLLMService
from ai_peer_review.services.openai_web_context_service import (
    fetch_proposal_review_web_context,
)
from ai_peer_review.services.proposal_review_comment_service import (
    upsert_proposal_review_comment,
)
from ai_peer_review.services.proposal_review_scoring import (
    normalize_category_scores_from_item_decisions,
    parse_json_response,
    recompute_overall_fields,
)
from ai_peer_review.services.researcher_external_context import (
    build_researcher_external_context,
)
from feed.views.funding_cache_mixin import FundingCacheMixin
from purchase.models import Grant, GrantApplication
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import PREREGISTRATION

logger = logging.getLogger(__name__)


def get_proposal_markdown(unified_document: ResearchhubUnifiedDocument) -> str:
    if unified_document.document_type != PREREGISTRATION:
        raise ValueError("Unified document must be a preregistration (proposal).")
    post = unified_document.posts.first()
    if not post:
        raise ValueError("Proposal post not found.")
    md = post.get_full_markdown()
    if md:
        return md
    return (post.renderable_text or post.title or "").strip()


def get_grant_context_text(grant: Grant) -> str:
    parts = []
    if grant.short_title:
        parts.append(f"Title: {grant.short_title}")
    if grant.organization:
        parts.append(f"Organization: {grant.organization}")
    parts.append(grant.description or "")
    post = grant.unified_document.posts.first()
    if post:
        body = post.get_full_markdown()
        if body:
            parts.append(body)
    return "\n\n".join(p for p in parts if p).strip()


def reset_proposal_review_for_rerun(review: ProposalReview) -> None:
    """Clear AI outputs so :func:`run_proposal_review` can run again."""
    review.status = ReviewStatus.PENDING
    review.error_message = ""
    review.result_data = {}
    review.overall_rating = None
    review.overall_rationale = ""
    review.overall_confidence = None
    review.overall_score_numeric = None
    review.save(
        update_fields=[
            "status",
            "error_message",
            "result_data",
            "overall_rating",
            "overall_rationale",
            "overall_confidence",
            "overall_score_numeric",
            "updated_date",
        ]
    )


def validate_grant_application(grant_id: int, unified_document_id: int) -> None:
    if not GrantApplication.objects.filter(
        grant_id=grant_id,
        preregistration_post__unified_document_id=unified_document_id,
    ).exists():
        raise ValueError(
            "This proposal is not linked to the given grant (no GrantApplication)."
        )


def run_proposal_review(review_id: int) -> None:
    review = ProposalReview.objects.select_related(
        "unified_document", "grant", "created_by"
    ).get(pk=review_id)
    if review.status == Status.COMPLETED:
        return
    t0 = time.monotonic()
    review.status = Status.PROCESSING
    review.progress = 10
    review.current_step = "Loading proposal text"
    review.error_message = ""
    review.save(
        update_fields=[
            "status",
            "progress",
            "current_step",
            "error_message",
            "updated_date",
        ]
    )
    try:
        proposal_text = get_proposal_markdown(review.unified_document)
        if not proposal_text.strip():
            raise ValueError("Proposal has no readable content.")
        rfp_context = None
        if review.grant_id:
            rfp_context = get_grant_context_text(review.grant)
        review.progress = 25
        review.current_step = "Loading researcher profile"
        review.save(update_fields=["progress", "current_step", "updated_date"])
        external_ctx = build_researcher_external_context(review.unified_document)
        author_ctx = build_author_context_snippet(review.unified_document)
        web_ctx = fetch_proposal_review_web_context(
            proposal_text,
            author_ctx or "",
        )
        review.progress = 40
        review.current_step = "Running AI assessment"
        review.save(update_fields=["progress", "current_step", "updated_date"])
        system = get_proposal_review_system_prompt()
        user = build_proposal_review_user_prompt(
            proposal_text,
            rfp_context,
            author_context=author_ctx or None,
            external_researcher_context=external_ctx or None,
            web_search_context=web_ctx or None,
        )
        llm = BedrockLLMService()
        raw = llm.invoke(
            system,
            user,
            max_tokens=PROPOSAL_REVIEW_MAX_OUTPUT_TOKENS,
            temperature=0.0,
        )
        review.progress = 70
        review.current_step = "Normalizing scores"
        review.save(update_fields=["progress", "current_step", "updated_date"])
        review_dict = parse_json_response(raw)
        normalize_category_scores_from_item_decisions(review_dict)
        recompute_overall_fields(review_dict)
        rating = review_dict["overall_rating"]
        numeric_total = review_dict["overall_score_numeric"]
        elapsed = time.monotonic() - t0
        review.status = Status.COMPLETED
        review.overall_rating = rating
        review.overall_rationale = review_dict.get("overall_rationale", "") or ""
        oc = review_dict.get("overall_confidence")
        review.overall_confidence = oc if oc in OverallConfidence.values else None
        review.overall_score_numeric = numeric_total
        review.result_data = review_dict
        review.llm_model = llm.model_id
        review.processing_time = elapsed
        review.progress = 100
        review.current_step = "Complete"
        review.save()
        try:
            upsert_proposal_review_comment(review)
        except Exception:
            logger.exception(
                "Proposal review %s comment sync failed",
                review_id,
            )
        FundingCacheMixin.invalidate_funding_feed_cache()
    except Exception as e:
        logger.exception("Proposal review %s failed", review_id)
        review.status = Status.FAILED
        review.error_message = str(e)[:4000]
        review.progress = 0
        review.current_step = "Failed"
        review.processing_time = time.monotonic() - t0
        review.save()
