import asyncio
import json
import logging
from datetime import datetime
from typing import Any

import redis
from asgiref.sync import async_to_sync
from channels.layers import BaseChannelLayer, get_channel_layer
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Model

from mailing_list.services import EmailService
from notification.models import Notification
from notification.serializers import (
    DynamicNotificationSerializer,
    get_notification_context,
)
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.models import User

logger = logging.getLogger(__name__)


class NotificationService:
    """Create inbox notifications and deliver email and live notification messages."""

    def __init__(
        self,
        email_service: EmailService | None = None,
        *,
        channel_layer: BaseChannelLayer | None = None,
        redis_client: redis.Redis | None = None,
    ) -> None:
        """Use the shared email service and configured live transports."""
        self._emails = email_service
        self._channel_layer = channel_layer
        self._redis_client = redis_client

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
        """Create a notification and send its selected channels after commit."""
        notification = Notification.objects.create(
            notification_type=notification_type,
            recipient=recipient,
            action_user=action_user,
            item=item,
            unified_document=unified_document,
            extra=extra or {},
        )
        transaction.on_commit(
            lambda: self._send_notification(notification), robust=True
        )
        if email_subject and email_message:
            self._email_recipient(
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
        """Skip an existing notice for this recipient and item within the cutoff."""
        previous = Notification.objects.filter(
            notification_type=notification_type,
            recipient=recipient,
            content_type=ContentType.objects.get_for_model(item),
            object_id=item.pk,
        )
        if since is not None:
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

    def try_send(
        self,
        notification_type: str,
        *,
        recipient: User,
        action_user: User,
        item: Model,
        unified_document: ResearchhubUnifiedDocument | None = None,
        extra: dict[str, Any] | None = None,
    ) -> Notification | None:
        """Isolate optional notification failures from the owning transaction."""
        try:
            with transaction.atomic():
                return self.send(
                    notification_type,
                    recipient=recipient,
                    action_user=action_user,
                    item=item,
                    unified_document=unified_document,
                    extra=extra,
                )
        except Exception:  # Existing moderation and payout notices are best effort.
            logger.exception(
                "Failed to create %s notification for %s %s",
                notification_type,
                type(item).__name__,
                item.pk,
            )
            return None

    def email_recipients(
        self, notification_ids: list[int], subject: str, message: str
    ) -> None:
        """Email the audience of existing notifications using their stored links."""
        notifications = Notification.objects.filter(
            id__in=notification_ids
        ).select_related("recipient", "unified_document")
        for notification in notifications.iterator():
            self._email_recipient(notification, subject, message)

    def _email_recipient(
        self,
        notification: Notification,
        subject: str,
        message: str,
        *,
        heading: str | None = None,
    ) -> None:
        """Email the recipient after commit with the notification's existing link."""
        link = notification.navigation_url
        if not link and notification.unified_document_id:
            link = notification.unified_document.frontend_view_link()
        if self._emails is None:
            self._emails = EmailService()
        transaction.on_commit(
            lambda: self._emails.send_notification_email(
                [notification.recipient.email],
                subject,
                message,
                link=link,
                heading=heading,
            ),
            robust=True,
        )

    def _send_notification(self, notification: Notification) -> bool:
        """Serialize an inbox row and publish its existing personal socket payload."""
        serialized_data = DynamicNotificationSerializer(
            notification,
            _include_fields=[
                "action_user",
                "body",
                "created_date",
                "extra",
                "id",
                "notification_type",
                "read",
                "read_date",
                "recipient",
            ],
            context=get_notification_context(),
        ).data
        return self.send_channel_message(
            f"notification_{notification.recipient_id}",
            {
                "type": "send_notification",
                "notification_type": notification.notification_type,
                "data": serialized_data,
            },
        )

    def send_channel_message(
        self, group: str, message: dict[str, Any], *, timeout: float | None = None
    ) -> bool:
        """Publish an existing Channels message from synchronous domain code."""

        async def _send() -> None:
            """Send the message within the synchronous caller's timeout."""
            layer = self._channel_layer or get_channel_layer()
            async with asyncio.timeout(timeout):
                await layer.group_send(group, message)

        try:
            async_to_sync(_send)()
            return True
        except Exception:  # Live transport failures must not interrupt domain work.
            logger.warning(
                "Failed to publish channel message to %s", group, exc_info=True
            )
            return False

    def publish_progress(self, channel: str, payload: dict[str, Any]) -> bool:
        """Publish an existing progress envelope through the shared Redis transport."""
        message = json.dumps(payload)
        if self._redis_client is None:
            host = getattr(settings, "REDIS_HOST", "localhost")
            port = getattr(settings, "REDIS_PORT", 6379)
            self._redis_client = redis.from_url(f"redis://{host}:{port}/3")
        try:
            self._redis_client.publish(channel, message)
            return True
        except redis.RedisError:
            logger.warning("Failed to publish progress to %s", channel, exc_info=True)
            return False
