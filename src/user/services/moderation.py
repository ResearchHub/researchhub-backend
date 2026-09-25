"""Shared moderator-action primitives used by the content and grant services.

Keeping the flag/verdict mechanics in one place means both
``ContentModerationService`` and ``GrantModerationService`` stay in lockstep
instead of maintaining parallel copies of the same logic.
"""

from django.db.models import Model

from discussion.models import Flag
from discussion.views import create_flag
from user.related_models.verdict_model import Verdict


def create_removal_verdict(
    moderator: Model, item: Model, reason: str = "", reason_choice: str = ""
) -> Flag:
    """Flag ``item`` and attach a content-removal verdict authored by ``moderator``.

    Returns the created flag (with ``verdict_created_date`` populated).
    """
    flag, _ = create_flag(
        user=moderator,
        item=item,
        reason=reason,
        reason_choice=reason_choice,
        reason_memo=reason,
    )

    verdict = Verdict.objects.create(
        created_by=moderator,
        flag=flag,
        verdict_choice=reason_choice,
        is_content_removed=True,
    )
    flag.verdict_created_date = verdict.created_date
    flag.save(update_fields=["verdict_created_date"])
    return flag
