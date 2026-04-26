import logging

from django.contrib.contenttypes.models import ContentType

from ai_peer_review.models import ProposalReview, ReviewStatus
from researchhub_comment.constants.rh_comment_content_types import TIPTAP
from researchhub_comment.constants.rh_comment_thread_types import COMMUNITY_REVIEW
from researchhub_comment.models import RhCommentModel, RhCommentThreadModel
from review.models import Review
from user.models import User

logger = logging.getLogger(__name__)

AI_EXPERT_EMAIL = "ai-review@researchhub.foundation"
AI_REVIEW_COMMENT_CONTEXT_TITLE = "AI Proposal Review"
AI_REVIEW_OVERALL_SUMMARY_TITLE = "Summary"


def get_ai_expert_user() -> User | None:
    return User.objects.filter(email=AI_EXPERT_EMAIL).first()


def _text_node(
    text: str,
    *,
    bold: bool = False,
    italic: bool = False,
) -> dict:
    node: dict = {"type": "text", "text": text}
    marks: list[dict] = []
    if bold:
        marks.append({"type": "bold"})
    if italic:
        marks.append({"type": "italic"})
    if marks:
        node["marks"] = marks
    return node


def _paragraph(
    text: str | None = None,
    bold: bool = False,
    italic: bool = False,
) -> dict:
    if not text:
        return {"type": "paragraph"}
    return {
        "type": "paragraph",
        "content": [_text_node(text, bold=bold, italic=italic)],
    }


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


_LABEL_IMPORTANCE = "Importance, significance, and innovation"
_LABEL_RIGOR = "Rigor & Feasibility"
_LABEL_ADDITIONAL = "Additional review criteria"


def _format_category_score_value(score) -> str:
    """``Score:`` value for a category: numeric 1–5 as ``n/5``, else string or N/A."""
    if score is None:
        return "N/A"
    if isinstance(score, (int, float)) and 1 <= float(score) <= 5:
        return f"{int(float(score))}/5"
    return str(score)


def _rationale_text(raw: object) -> str:
    if raw is None:
        return ""
    return str(raw).strip()


def _item_key_to_label(snake: str) -> str:
    """e.g. ``question_importance`` -> ``Question Importance``."""
    if not snake:
        return ""
    return " ".join(part.capitalize() for part in str(snake).split("_") if part)


def _list_item_bold_italic_bullet(item_key: str, justification: str) -> dict:
    """``{Label}: {justification}`` with label bold, justification italic."""
    label = _item_key_to_label(item_key)
    return {
        "type": "listItem",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    _text_node(label, bold=True),
                    _text_node(": "),
                    _text_node(justification, italic=True),
                ],
            }
        ],
    }


def _append_category_item_bullets(
    body: list[dict],
    category: dict,
) -> None:
    """
    One bullet list per category: each item is **Label**: *justification*.

    Skips non-dict item rows or rows with no justification and no decision string.
    """
    raw = category.get("items")
    if not isinstance(raw, dict) or not raw:
        return
    out: list[dict] = []
    for key in sorted(raw.keys(), key=str):
        row = raw.get(key)
        if not isinstance(row, dict):
            continue
        j = _rationale_text(row.get("justification"))
        if not j:
            j = _rationale_text(row.get("decision"))
        if not j:
            continue
        out.append(_list_item_bold_italic_bullet(str(key), j))
    if not out:
        return
    body.append({"type": "bulletList", "content": out})


def _append_title_and_rationale(
    body: list[dict],
    *,
    title_bold: str,
    category_rationale: object,
) -> None:
    body.append(_paragraph(title_bold, bold=True))
    t = _rationale_text(category_rationale)
    if t:
        body.append(_paragraph(t))


def _omit_fatal_flaws_section(raw) -> bool:
    """Omit the Fatal flaws block for ``[]``, missing, or a sole ``"None"``-style entry."""
    if raw is None:
        return True
    if not isinstance(raw, list):
        return True
    items = [x.strip() for x in (str(s) for s in raw) if x.strip()]
    if not items:
        return True
    if len(items) == 1 and items[0].lower() in ("none", "n/a", "n/a."):
        return True
    return False


def proposal_review_to_tiptap_content(review: ProposalReview) -> dict:
    result_data = review.result_data or {}
    categories = result_data.get("categories") or {}
    raw_fatal = result_data.get("fatal_flaws")

    impact = categories.get("overall_impact") or {}
    importance = categories.get("importance_significance_innovation") or {}
    rigor = categories.get("rigor_and_feasibility") or {}
    additional = categories.get("additional_review_criteria") or {}

    impact_rationale = _rationale_text(impact.get("rationale"))

    body: list[dict] = []
    _append_title_and_rationale(
        body,
        title_bold=f"1. Overall Impact. Score: {_format_category_score_value(impact.get('score'))}",
        category_rationale=impact_rationale or None,
    )
    _append_category_item_bullets(body, impact)

    show_core_header = (
        importance.get("score") is not None or rigor.get("score") is not None
    )
    if show_core_header:
        body.append(_paragraph("2. Core Review Factors", bold=True))

    if importance.get("score") is not None:
        _append_title_and_rationale(
            body,
            title_bold=(
                f"2.a {_LABEL_IMPORTANCE}. "
                f"Score: {_format_category_score_value(importance.get('score'))}"
            ),
            category_rationale=importance.get("rationale"),
        )
        _append_category_item_bullets(body, importance)
    if rigor.get("score") is not None:
        _append_title_and_rationale(
            body,
            title_bold=(
                f"2.b {_LABEL_RIGOR}. "
                f"Score: {_format_category_score_value(rigor.get('score'))}"
            ),
            category_rationale=rigor.get("rationale"),
        )
        _append_category_item_bullets(body, rigor)
    if additional.get("score") is not None:
        _append_title_and_rationale(
            body,
            title_bold=(
                f"3. {_LABEL_ADDITIONAL}. "
                f"Score: {_format_category_score_value(additional.get('score'))}"
            ),
            category_rationale=additional.get("rationale"),
        )
        _append_category_item_bullets(body, additional)
    if not _omit_fatal_flaws_section(raw_fatal):
        items = [str(s).strip() for s in (raw_fatal or []) if str(s).strip()]
        body.append(_paragraph("Fatal flaws", bold=True, italic=True))
        body.append(_bullet_list(items[:5]))
    summary_text = _rationale_text(result_data.get("overall_summary"))
    if summary_text:
        body.append(_paragraph(AI_REVIEW_OVERALL_SUMMARY_TITLE, bold=True))
        body.append(_paragraph(summary_text))
    body.append(_paragraph())

    return {"type": "doc", "content": body}


def _review_thread_reference(review: ProposalReview) -> str:
    grant_part = review.grant_id if review.grant_id is not None else "standalone"
    return f"ai_proposal_review:{review.unified_document_id}:{grant_part}"


def get_proposal_review_ai_expert_comment(
    review: ProposalReview,
) -> RhCommentModel | None:
    """
    The AI proposal review :class:`RhCommentModel` for this review, if it exists
    (same location :func:`upsert_proposal_review_comment` would read or write).
    Does not create threads, users, or comments.
    """
    post = review.unified_document.posts.first()
    if post is None:
        return None
    ai_user = get_ai_expert_user()
    if ai_user is None:
        return None
    content_type = ContentType.objects.get_for_model(post)
    thread = RhCommentThreadModel.objects.filter(
        content_type=content_type,
        object_id=post.id,
        thread_type=COMMUNITY_REVIEW,
        thread_reference=_review_thread_reference(review),
    ).first()
    if thread is None:
        return None
    return (
        RhCommentModel.objects.filter(
            thread=thread,
            parent__isnull=True,
            created_by=ai_user,
        )
        .order_by("created_date")
        .first()
    )


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
        thread_type=COMMUNITY_REVIEW,
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
            comment_type=COMMUNITY_REVIEW,
            comment_content_type=TIPTAP,
            comment_content_json=tiptap_content,
        )
        comment.refresh_related_discussion_count()
    else:
        comment.updated_by = ai_user
        comment.context_title = AI_REVIEW_COMMENT_CONTEXT_TITLE
        comment.comment_type = COMMUNITY_REVIEW
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
