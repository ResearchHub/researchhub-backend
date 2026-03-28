"""
Proposal review: load proposal/RFP text, call Bedrock, normalize scores, persist.
"""

import logging
import time

from django.conf import settings
from research_ai.constants import ReviewStatus
from research_ai.models import ProposalReview
from research_ai.prompts.proposal_review_prompts import (
    build_proposal_review_user_prompt,
    get_proposal_review_system_prompt,
)
from research_ai.services.bedrock_llm_service import BEDROCK_MODEL_ID, BedrockLLMService
from research_ai.services.proposal_review_scoring import (
    compute_overall_rating,
    normalize_scores_from_answers,
    parse_json_response,
)
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from researchhub_document.models import ResearchhubUnifiedDocument
from purchase.models import Grant, GrantApplication

logger = logging.getLogger(__name__)


def get_proposal_markdown(unified_document: ResearchhubUnifiedDocument) -> str:
    if unified_document.document_type != PREREGISTRATION:
        raise ValueError(
            "Unified document must be a preregistration (proposal)."
        )
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


def validate_grant_application(
    grant_id: int, unified_document_id: int
) -> None:
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
    if review.status == ReviewStatus.COMPLETED:
        return
    t0 = time.monotonic()
    review.status = ReviewStatus.PROCESSING
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
        review.progress = 40
        review.current_step = "Running AI assessment"
        review.save(
            update_fields=["progress", "current_step", "updated_date"]
        )
        system = get_proposal_review_system_prompt()
        user = build_proposal_review_user_prompt(proposal_text, rfp_context)
        llm = BedrockLLMService()
        raw = llm.invoke(
            system,
            user,
            max_tokens=min(16384, getattr(settings, "RESEARCH_AI_PROPOSAL_REVIEW_MAX_TOKENS", 16384)),
            temperature=0.0,
        )
        review.progress = 70
        review.current_step = "Normalizing scores"
        review.save(
            update_fields=["progress", "current_step", "updated_date"]
        )
        review_dict = parse_json_response(raw)
        normalize_scores_from_answers(review_dict)
        rating, numeric_total = compute_overall_rating(review_dict)
        review_dict["overall_rating"] = rating
        review_dict["overall_score_numeric"] = numeric_total
        elapsed = time.monotonic() - t0
        review.status = ReviewStatus.COMPLETED
        review.overall_rating = rating
        review.overall_score_numeric = numeric_total
        review.result_data = review_dict
        review.llm_model = getattr(
            settings, "RESEARCH_AI_BEDROCK_MODEL_ID", BEDROCK_MODEL_ID
        )
        review.processing_time = elapsed
        review.progress = 100
        review.current_step = "Complete"
        review.save()
    except Exception as e:
        logger.exception("Proposal review %s failed", review_id)
        review.status = ReviewStatus.FAILED
        review.error_message = str(e)[:4000]
        review.progress = 0
        review.current_step = "Failed"
        review.processing_time = time.monotonic() - t0
        review.save()
