"""Resolve the author and risk-score source behind a moderator removal verdict.

Shared by the real-time risk-score signal and the backfill command so both
attribute censorship identically.
"""

from django.db.models import Model

from paper.related_models.paper_model import Paper
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from user.related_models.user_model import User
from user.related_models.verdict_model import Verdict

DECLINED_STATUS = "DECLINED"


def _flagged_content(verdict: Verdict) -> Model | None:
    model_class = verdict.flag.content_type.model_class()
    if model_class is None:
        return None
    manager = getattr(model_class, "all_objects", model_class.objects)
    return manager.filter(pk=verdict.flag.object_id).first()


def resolve_censorship(verdict: Verdict) -> tuple[User | None, Model | None]:
    """Return (author, source) for the content a verdict removed, or (None, None)
    when it shouldn't be scored as censorship.

    Declined works are skipped: a decline already scores WORK_DECLINED, so
    scoring it again as CONTENT_CENSORED would double-penalize the author.
    `source` matches how the events API resolves detail: comments score against
    themselves, documents against their unified_document.
    """
    content = _flagged_content(verdict)
    if content is None:
        return None, None

    if isinstance(content, RhCommentModel):
        return content.created_by, content

    unified_document = getattr(content, "unified_document", None)
    declined = DECLINED_STATUS in (
        getattr(content, "status", None),
        getattr(unified_document, "status", None),
    )
    if declined:
        return None, None

    if isinstance(content, Paper):
        author = content.uploaded_by
    else:
        author = getattr(content, "created_by", None)
    return author, unified_document
