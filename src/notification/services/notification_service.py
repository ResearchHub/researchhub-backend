import logging
from datetime import datetime
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Model

from mailing_list.services import EmailService
from notification.models import Notification
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.models import User

logger = logging.getLogger(__name__)


class NotificationService:
    """Create, push, and optionally email a notification."""

    def __init__(self, email_service: EmailService | None = None) -> None:
        self._emails = email_service or EmailService()

    def send(
        self,
        notification_type: str,
        *,
        recipient: User,
        action_user: User,
        item: Model,
        unified_document: ResearchhubUnifiedDocument | None = None,
        extra: dict[str, Any] | None = None,
        email_subject: str | None = None,
        email_heading: str | None = None,
        email_message: str | None = None,
    ) -> Notification:
        """
        Create the notification and push it to the recipient over the websocket.

        The recipient is also emailed when `email_subject` and `email_message`
        are given.
        """
        notification = self._create(
            notification_type,
            recipient=recipient,
            action_user=action_user,
            item=item,
            unified_document=unified_document,
            extra=extra,
        )
        notification.send_notification()

        if email_subject and email_message:
            self.email_recipient(
                notification, email_subject, email_message, heading=email_heading
            )

        return notification

    def send_once(
        self,
        notification_type: str,
        *,
        recipient: User,
        action_user: User,
        item: Model,
        unified_document: ResearchhubUnifiedDocument | None = None,
        extra: dict[str, Any] | None = None,
        email_subject: str | None = None,
        email_heading: str | None = None,
        email_message: str | None = None,
        since: datetime | None = None,
    ) -> Notification | None:
        """
        Send unless the recipient already has this notification for this item.

        Returns `None` when it was already sent. Pass `since` to ignore older
        rows so a reminder can recur after that cutoff.
        """
        previous = Notification.objects.filter(
            notification_type=notification_type,
            recipient=recipient,
            content_type=ContentType.objects.get_for_model(item),
            object_id=item.id,
        )

        if since:
            previous = previous.filter(created_date__gte=since)

        if previous.exists():
            return None

        return self.send(
            notification_type,
            recipient=recipient,
            action_user=action_user,
            item=item,
            unified_document=unified_document,
            extra=extra,
            email_subject=email_subject,
            email_heading=email_heading,
            email_message=email_message,
        )

    def send_after_commit(
        self,
        notification_type: str,
        *,
        recipient: User,
        action_user: User,
        item: Model,
        unified_document: ResearchhubUnifiedDocument | None = None,
        extra: dict[str, Any] | None = None,
    ) -> Notification | None:
        """
        Create the notification now; push it only after the surrounding
        transaction commits.

        Logs failures and returns `None` so a broken notification cannot undo
        the action that triggered it.
        """
        try:
            notification = self._create(
                notification_type,
                recipient=recipient,
                action_user=action_user,
                item=item,
                unified_document=unified_document,
                extra=extra,
            )
        except Exception:
            logger.exception(
                "Failed to create %s notification for %s %s",
                notification_type,
                type(item).__name__,
                item.id,
            )
            return None

        transaction.on_commit(notification.send_notification, robust=True)

        return notification

    def email_recipient(
        self,
        notification: Notification,
        subject: str,
        message: str,
        *,
        heading: str | None = None,
    ) -> None:
        """
        Email the message with a button linking to what the notification is about.

        Types without a formatted `navigation_url` link to the document when
        one is set; otherwise the email has no View button.
        """
        link = notification.navigation_url
        if not link and notification.unified_document_id:
            link = notification.unified_document.frontend_view_link()

        self._emails.send_notification_email(
            [notification.recipient.email],
            subject,
            message,
            link=link,
            heading=heading,
        )

    def _create(
        self,
        notification_type: str,
        *,
        recipient: User,
        action_user: User,
        item: Model,
        unified_document: ResearchhubUnifiedDocument | None,
        extra: dict[str, Any] | None,
    ) -> Notification:
        """Persist the notification row pointing at `item`."""
        return Notification.objects.create(
            notification_type=notification_type,
            recipient=recipient,
            action_user=action_user,
            item=item,
            unified_document=unified_document,
            extra=extra or {},
        )
