import logging
import time

from django.utils import timezone

from ai_peer_review.constants import CATEGORY_KEYS
from ai_peer_review.models import ProposalReview, ReviewStatus, RFPSummary
from ai_peer_review.prompts.rfp_summary_prompts import (
    build_rfp_summary_user_prompt,
    get_grant_executive_summary_system_prompt,
    get_rfp_summary_system_prompt,
)
from ai_peer_review.services.bedrock_llm_service import BedrockLLMService
from ai_peer_review.services.proposal_review_scoring import category_scores
from feed.views.funding_cache_mixin import FundingCacheMixin
from purchase.models import Grant

logger = logging.getLogger(__name__)


def get_grant_source_text(grant: Grant) -> str:
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


def run_rfp_summary(rfp_summary_id: int) -> None:
    obj = RFPSummary.objects.select_related("grant").get(pk=rfp_summary_id)
    if obj.status == ReviewStatus.COMPLETED and obj.summary_content.strip():
        return
    t0 = time.monotonic()
    obj.status = ReviewStatus.PROCESSING
    obj.error_message = ""
    obj.save(update_fields=["status", "error_message", "updated_date"])
    try:
        text = get_grant_source_text(obj.grant)
        if not text.strip():
            raise ValueError("Grant has no readable description or post body.")
        llm = BedrockLLMService()
        out = llm.invoke(
            get_rfp_summary_system_prompt(),
            build_rfp_summary_user_prompt(text),
            max_tokens=8192,
            temperature=0.0,
        )
        obj.summary_content = out.strip()
        obj.status = ReviewStatus.COMPLETED
        obj.llm_model = llm.model_id
        obj.processing_time = time.monotonic() - t0
        obj.save()
    except Exception as e:
        logger.exception("RFP summary %s failed", rfp_summary_id)
        obj.status = ReviewStatus.FAILED
        obj.error_message = str(e)[:4000]
        obj.processing_time = time.monotonic() - t0
        obj.save()


def run_executive_comparison(
    grant_id: int, created_by_id: int | None = None
) -> RFPSummary:
    grant = Grant.objects.get(pk=grant_id)
    reviews = (
        ProposalReview.objects.filter(
            grant_id=grant_id,
            status=ReviewStatus.COMPLETED,
        )
        .select_related("unified_document")
        .order_by("-overall_score_numeric", "id")
    )
    lines = []
    for r in reviews:
        ud = r.unified_document
        post = ud.posts.first()
        title = (post.title if post else "") or f"Document {ud.id}"
        cats = category_scores(r.result_data or {})
        cat_parts = [f"{k}={cats.get(k)}" for k in CATEGORY_KEYS]
        snippet = ((r.result_data or {}).get("overall_summary") or "")[:400]
        lines.append(
            f"- Title: {title[:200]}\n"
            "  Overall: "
            f"{r.overall_rating} (numeric {r.overall_score_numeric}, scale 1-5)\n"
            f"  Categories: {', '.join(cat_parts)}\n"
            f"  Summary snippet: {snippet}"
        )
    if not lines:
        raise ValueError(
            "No completed proposal reviews for this grant. Run proposal reviews first."
        )
    user_prompt = (
        "Funding opportunity (context):\n"
        + get_grant_source_text(grant)[:6000]
        + "\n\n---\nProposals and scores:\n"
        + "\n".join(lines)
    )
    llm = BedrockLLMService()
    out = llm.invoke(
        get_grant_executive_summary_system_prompt(),
        user_prompt,
        max_tokens=4096,
        temperature=0.2,
    )
    defaults: dict = {"status": ReviewStatus.PENDING}
    if created_by_id is not None:
        defaults["created_by_id"] = created_by_id
    obj, _ = RFPSummary.objects.get_or_create(
        grant=grant,
        defaults=defaults,
    )
    obj.executive_comparison_summary = out.strip()
    obj.executive_comparison_updated_date = timezone.now()
    obj.status = ReviewStatus.COMPLETED
    obj.error_message = ""
    obj.llm_model = llm.model_id
    obj.save(
        update_fields=[
            "executive_comparison_summary",
            "executive_comparison_updated_date",
            "status",
            "error_message",
            "llm_model",
            "updated_date",
        ]
    )
    FundingCacheMixin.invalidate_funding_feed_cache()
    return obj
