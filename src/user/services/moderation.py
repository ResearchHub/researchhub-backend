"""Shared moderator-action primitives used by the content and grant services.

Keeping the flag/verdict and notification mechanics in one place means both
``ContentModerationService`` and ``GrantModerationService`` stay in lockstep
instead of maintaining parallel copies of the same logic.
"""

import logging

from django.contrib.contenttypes.models import ContentType
from django.db.models import Model

from discussion.models import Flag
from discussion.views import create_flag
from notification.models import Notification
from user.related_models.verdict_model import Verdict

logger = logging.getLogger(__name__)


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


def send_moderation_notification(
    notification_type: str, *, recipient: Model, action_user: Model, item: Model
) -> None:
    """Create and dispatch a moderation notification, logging (never raising)
    on failure so a notification bug can't roll back the moderation action."""
    try:
        notification = Notification.objects.create(
            notification_type=notification_type,
            recipient=recipient,
            action_user=action_user,
            content_type=ContentType.objects.get_for_model(item),
            object_id=item.id,
            unified_document=item.unified_document,
        )
        notification.send_notification()
    except Exception:
        logger.exception(
            "Failed to send %s notification for %s %s",
            notification_type,
            type(item).__name__,
            item.id,
        )
