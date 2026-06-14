from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import transaction
from django.utils import timezone

from feed.tasks import publish_to_feed
from notification.models import Notification
from paper.related_models.paper_model import Paper
from purchase.services.grant_service import GrantModerationService
from researchhub_document.related_models.constants.document_type import GRANT
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.services.moderation import (
    create_removal_verdict,
    send_moderation_notification,
)

if TYPE_CHECKING:
    from purchase.models import Grant
    from user.models import User

# A work this service can moderate directly (grants are delegated to
# GrantModerationService). Papers and posts gate visibility through their
# unified document's moderation status.
ModerationTarget = ResearchhubPost | Paper


class ContentModerationService:
    """Approve or decline works awaiting moderation: posts, proposals, papers.

    Moderation status lives on the unified document, so approving a work no
    longer fires the ResearchhubPost create signal. Both papers and posts are
    therefore published here explicitly on approval, the same way grants publish
    in ``GrantModerationService`` (grants stay delegated to that service).

    Declining soft-deletes the unified document, which unpublishes the work via
    the ``handle_unified_document_removed`` signal.
    """

    def __init__(self) -> None:
        self._grant_service = GrantModerationService()

    def approve_content(
        self, content: ModerationTarget, moderator: User
    ) -> ModerationTarget:
        """Approve pending content and publish the approved work to the feed."""
        if self._is_grant(content):
            self._grant_service.approve_grant(self._grant_for(content), moderator)
            return content

        self._require_pending(content, "approved")

        with transaction.atomic():
            self._mark_reviewed(content, moderator, ResearchhubUnifiedDocument.APPROVED)
            self._publish(content)
            self._notify(content, moderator, Notification.CONTENT_APPROVED)

        return content

    def decline_content(
        self,
        content: ModerationTarget,
        moderator: User,
        reason: str = "",
        reason_choice: str = "",
    ) -> ModerationTarget:
        """Decline pending content, flag it, and soft-delete its unified document."""
        if self._is_grant(content):
            self._grant_service.decline_grant(
                self._grant_for(content), moderator, reason, reason_choice
            )
            return content

        self._require_pending(content, "declined")

        with transaction.atomic():
            self._mark_reviewed(content, moderator, ResearchhubUnifiedDocument.DECLINED)
            self._flag_and_remove(content, moderator, reason, reason_choice)
            self._notify(content, moderator, Notification.CONTENT_DECLINED)

        return content

    def _is_grant(self, content: ModerationTarget) -> bool:
        return isinstance(content, ResearchhubPost) and content.document_type == GRANT

    def _require_pending(self, content: ModerationTarget, past_tense: str) -> None:
        if content.unified_document.status != ResearchhubUnifiedDocument.PENDING:
            raise ValueError(f"Only pending content can be {past_tense}")

    def _grant_for(self, content: ModerationTarget) -> Grant:
        grant = content.unified_document.grants.first()
        if grant is None:
            raise ValueError("Grant content has no associated grant to moderate")
        return grant

    def _author(self, content: ModerationTarget) -> User | None:
        return content.uploaded_by if isinstance(content, Paper) else content.created_by

    def _mark_reviewed(
        self, content: ModerationTarget, moderator: User, status: str
    ) -> None:
        unified_document = content.unified_document
        unified_document.status = status
        unified_document.reviewed_by = moderator
        unified_document.reviewed_date = timezone.now()
        unified_document.save(update_fields=["status", "reviewed_by", "reviewed_date"])

    def _publish(self, content: ModerationTarget) -> None:
        author = self._author(content)
        publish_to_feed(content, author.id if author else None)

    def _flag_and_remove(
        self,
        content: ModerationTarget,
        moderator: User,
        reason: str,
        reason_choice: str,
    ) -> None:
        create_removal_verdict(moderator, content, reason, reason_choice)

        # A paper is its own item, so it must be removed alongside its document.
        if isinstance(content, Paper):
            content.is_removed = True
            content.save(update_fields=["is_removed"])

        unified_document = content.unified_document
        unified_document.is_removed = True
        unified_document.save(update_fields=["is_removed"])

    def _notify(
        self, content: ModerationTarget, action_user: User, notification_type: str
    ) -> None:
        send_moderation_notification(
            notification_type,
            recipient=self._author(content),
            action_user=action_user,
            item=content,
        )
