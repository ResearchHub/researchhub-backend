import logging

from django.contrib.contenttypes.models import ContentType

from ai_peer_review.models import ProposalReview, ReviewStatus
from researchhub_comment.constants.rh_comment_content_types import TIPTAP
from researchhub_comment.models import RhCommentModel, RhCommentThreadModel
from review.models import Review
from user.models import User

logger = logging.getLogger(__name__)

AI_EXPERT_EMAIL = "ai-review@researchhub.foundation"
AI_REVIEW_COMMENT_CONTEXT_TITLE = "AI Proposal Review"
AI_REVIEW_COMMENT_TYPE = "REVIEW"


def get_ai_expert_user() -> User | None:
    return User.objects.filter(email=AI_EXPERT_EMAIL).first()


def proposal_review_to_plain_text(review: ProposalReview) -> str:
    result_data = review.result_data or {}
    categories = result_data.get("categories") or {}
    significance_score = categories.get("importance_significance_innovation", {}).get(
        "score",
        "N/A",
    )
    major_strengths = result_data.get("major_strengths") or []
    major_weaknesses = result_data.get("major_weaknesses") or []
    fatal_flaws = result_data.get("fatal_flaws") or []

    lines = [
        "AI Proposal Review",
        "",
        f"Overall rating: {review.overall_rating or 'N/A'}",
        f"Overall score: {review.overall_score_numeric or 'N/A'}/5",
        f"Confidence: {review.overall_confidence or 'N/A'}",
        "",
        f"Rationale: {review.overall_rationale or ''}",
        "",
        "Category scores:",
        f"- Overall impact: {categories.get('overall_impact', {}).get('score', 'N/A')}",
        ("- Importance/significance/innovation: " f"{significance_score}"),
        (
            "- Rigor and feasibility: "
            f"{categories.get('rigor_and_feasibility', {}).get('score', 'N/A')}"
        ),
        (
            "- Additional review criteria: "
            f"{categories.get('additional_review_criteria', {}).get('score', 'N/A')}"
        ),
        "",
        "Major strengths:",
    ]

    lines.extend(f"- {item}" for item in major_strengths[:5])
    if not major_strengths:
        lines.append("- N/A")

    lines.append("")
    lines.append("Major weaknesses:")
    lines.extend(f"- {item}" for item in major_weaknesses[:5])
    if not major_weaknesses:
        lines.append("- N/A")

    lines.append("")
    lines.append("Fatal flaws:")
    lines.extend(f"- {item}" for item in fatal_flaws[:5])
    if not fatal_flaws:
        lines.append("- None")

    return "\n".join(lines).strip()


def _paragraph(text: str | None = None, bold: bool = False) -> dict:
    if not text:
        return {"type": "paragraph"}
    text_node = {"type": "text", "text": text}
    if bold:
        text_node["marks"] = [{"type": "bold"}]
    return {"type": "paragraph", "content": [text_node]}


def _bullet_list(items: list[str]) -> dict:
    return {
        "type": "bulletList",
        "content": [
            {
                "type": "listItem",
                "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": i}]}
                ],
            }
            for i in items
        ],
    }


def _ordered_list(items: list[str]) -> dict:
    return {
        "type": "orderedList",
        "attrs": {"start": 1, "type": None},
        "content": [
            {
                "type": "listItem",
                "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": i}]}
                ],
            }
            for i in items
        ],
    }


def proposal_review_to_tiptap_content(review: ProposalReview) -> dict:
    result_data = review.result_data or {}
    categories = result_data.get("categories") or {}
    strengths = result_data.get("major_strengths") or ["N/A"]
    weaknesses = result_data.get("major_weaknesses") or ["N/A"]
    fatal_flaws = result_data.get("fatal_flaws") or ["None"]
    rationale_text = review.overall_rationale or "No rationale available."

    category_rows = [
        f"Overall impact: {categories.get('overall_impact', {}).get('score', 'N/A')}",
        (
            "Importance/significance/innovation: "
            f"{categories.get('importance_significance_innovation', {}).get('score', 'N/A')}"
        ),
        f"Rigor and feasibility: {categories.get('rigor_and_feasibility', {}).get('score', 'N/A')}",
        (
            "Additional review criteria: "
            f"{categories.get('additional_review_criteria', {}).get('score', 'N/A')}"
        ),
    ]

    return {
        "type": "doc",
        "content": [
            _paragraph(AI_REVIEW_COMMENT_CONTEXT_TITLE, bold=True),
            _paragraph(
                f"Overall rating: {review.overall_rating or 'N/A'} | "
                f"Overall score: {review.overall_score_numeric or 'N/A'}/5 | "
                f"Confidence: {review.overall_confidence or 'N/A'}"
            ),
            _paragraph("Rationale", bold=True),
            {
                "type": "blockquote",
                "content": [_paragraph(rationale_text)],
            },
            _paragraph("Category scores", bold=True),
            _bullet_list(category_rows),
            _paragraph("Major strengths", bold=True),
            _ordered_list(strengths[:5]),
            _paragraph("Major weaknesses", bold=True),
            _ordered_list(weaknesses[:5]),
            _paragraph("Fatal flaws", bold=True),
            _bullet_list(fatal_flaws[:5]),
            _paragraph(),
        ],
    }


def _review_thread_reference(review: ProposalReview) -> str:
    grant_part = review.grant_id if review.grant_id is not None else "standalone"
    return f"ai_proposal_review:{review.unified_document_id}:{grant_part}"


def proposal_overall_numeric_to_review_score(
    overall_score_numeric: int | None,
) -> float:
    """
    Map ``ProposalReview.overall_score_numeric`` (1-5) to ``Review.score``.

    ``Review.score`` allows 1-10, but proposal overalls are on a 1-5 scale; we
    store the numeric as-is for now (still valid) so the UI and DB stay aligned.
    """
    if overall_score_numeric is None:
        return 1.0
    try:
        n = int(overall_score_numeric)
    except (TypeError, ValueError):
        return 1.0
    if n < 1:
        return 1.0
    if n > 5:
        return 5.0
    return float(n)


def upsert_proposal_review_comment(review: ProposalReview) -> RhCommentModel | None:
    if review.status != ReviewStatus.COMPLETED:
        return None

    post = review.unified_document.posts.first()
    if post is None:
        return None

    ai_user = get_ai_expert_user()
    if ai_user is None:
        logger.warning(
            "AI expert user missing for proposal review comment sync "
            "(expected email=%s)",
            AI_EXPERT_EMAIL,
        )
        return None
    content_type = ContentType.objects.get_for_model(post)
    thread_reference = _review_thread_reference(review)

    thread, _ = RhCommentThreadModel.objects.get_or_create(
        content_type=content_type,
        object_id=post.id,
        thread_type=AI_REVIEW_COMMENT_TYPE,
        thread_reference=thread_reference,
        defaults={
            "created_by": ai_user,
            "updated_by": ai_user,
        },
    )

    tiptap_content = proposal_review_to_tiptap_content(review)

    comment = (
        RhCommentModel.objects.filter(
            thread=thread,
            parent__isnull=True,
            created_by=ai_user,
        )
        .order_by("created_date")
        .first()
    )

    if comment is None:
        comment = RhCommentModel.objects.create(
            thread=thread,
            created_by=ai_user,
            updated_by=ai_user,
            context_title=AI_REVIEW_COMMENT_CONTEXT_TITLE,
            comment_type=AI_REVIEW_COMMENT_TYPE,
            comment_content_type=TIPTAP,
            comment_content_json=tiptap_content,
        )
        comment.refresh_related_discussion_count()
    else:
        comment.updated_by = ai_user
        comment.context_title = AI_REVIEW_COMMENT_CONTEXT_TITLE
        comment.comment_type = AI_REVIEW_COMMENT_TYPE
        comment.comment_content_type = TIPTAP
        comment.comment_content_json = tiptap_content
        comment.save(
            update_fields=[
                "updated_by",
                "context_title",
                "comment_type",
                "comment_content_type",
                "comment_content_json",
                "updated_date",
            ]
        )

    comment.update_comment_content()

    comment_ct = ContentType.objects.get_for_model(RhCommentModel)
    Review.objects.update_or_create(
        content_type=comment_ct,
        object_id=comment.id,
        defaults={
            "unified_document": review.unified_document,
            "created_by": ai_user,
            "score": proposal_overall_numeric_to_review_score(
                review.overall_score_numeric
            ),
            "is_removed": False,
        },
    )
    return comment
