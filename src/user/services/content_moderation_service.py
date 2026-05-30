import logging

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from discussion.views import create_flag
from feed.tasks import publish_to_feed
from notification.models import Notification
from paper.related_models.paper_model import Paper
from purchase.services.grant_service import GrantModerationService
from researchhub_document.related_models.constants.document_type import GRANT
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from user.related_models.verdict_model import Verdict

logger = logging.getLogger(__name__)


class ContentModerationService:
    """Approve or decline works awaiting moderation: posts, proposals, papers.

    Publishing reuses each content type's existing path so there's a single
    source of truth per type:

    * Posts/proposals publish via the ResearchhubPost ``post_save`` signal the
      moment their status flips to APPROVED -- nothing to do here.
    * Papers have no status-driven publish signal, so they're published here
      explicitly, the same way grants publish in ``GrantModerationService``.
    * Grants are delegated entirely to ``GrantModerationService``.

    Declining soft-deletes the unified document, which unpublishes the work via
    the ``handle_unified_document_removed`` signal.
    """

    def __init__(self):
        self._grant_service = GrantModerationService()

    def approve_content(self, content, moderator):
        """Approve pending content; publication is handled per type (see class docs)."""
        if self._is_grant(content):
            self._grant_service.approve_grant(self._grant_for(content), moderator)
            return content

        self._require_pending(content, "approved")

        with transaction.atomic():
            self._mark_reviewed(content, moderator, content.APPROVED)
            # Papers have no publish-on-approval signal, so publish them here.
            if isinstance(content, Paper):
                publish_to_feed(content, content.uploaded_by_id)
            self._notify(content, moderator, Notification.CONTENT_APPROVED)

        return content

    def decline_content(self, content, moderator, reason="", reason_choice=""):
        """Decline pending content, flag it, and soft-delete its unified document."""
        if self._is_grant(content):
            self._grant_service.decline_grant(
                self._grant_for(content), moderator, reason, reason_choice
            )
            return content

        self._require_pending(content, "declined")

        with transaction.atomic():
            self._mark_reviewed(content, moderator, content.DECLINED)
            self._flag_and_remove(content, moderator, reason, reason_choice)
            self._notify(content, moderator, Notification.CONTENT_DECLINED)

        return content

    def _is_grant(self, content):
        return isinstance(content, ResearchhubPost) and content.document_type == GRANT

    def _require_pending(self, content, action):
        if content.status != content.PENDING:
            raise ValueError(f"Only pending content can be {action}")

    def _grant_for(self, content):
        return content.unified_document.grants.first()

    def _author(self, content):
        return content.uploaded_by if isinstance(content, Paper) else content.created_by

    def _mark_reviewed(self, content, moderator, status):
        content.status = status
        content.reviewed_by = moderator
        content.reviewed_date = timezone.now()
        content.save(update_fields=["status", "reviewed_by", "reviewed_date"])

    def _flag_and_remove(self, content, moderator, reason, reason_choice):
        flag, _ = create_flag(
            user=moderator,
            item=content,
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

        if isinstance(content, Paper):
            content.is_removed = True
            content.save(update_fields=["is_removed"])

        unified_document = content.unified_document
        unified_document.is_removed = True
        unified_document.save(update_fields=["is_removed"])

    def _notify(self, content, action_user, notification_type):
        try:
            notification = Notification.objects.create(
                notification_type=notification_type,
                recipient=self._author(content),
                action_user=action_user,
                content_type=ContentType.objects.get_for_model(content),
                object_id=content.id,
                unified_document=content.unified_document,
            )
            notification.send_notification()
        except Exception:
            logger.exception(
                "Failed to send %s notification for %s %s",
                notification_type,
                type(content).__name__,
                content.id,
            )
