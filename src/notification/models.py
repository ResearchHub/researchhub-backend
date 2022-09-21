from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib.postgres.fields import ArrayField, HStoreField
from django.db import models

from researchhub.settings import BASE_FRONTEND_URL
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.models import Action, User

"""
<QuerySet ['comment', 'reply', 'thread', 'summary', 'withdrawal', 'bulletpoint', 'purchase', 'vote', 'vote', 'verdict', 'bounty']>
"""


class Notification(models.Model):
    THREAD_ON_DOC = "THREAD_ON_DOC"
    COMMENT_ON_THREAD = "COMMENT_ON_THREAD"
    REPLY_ON_THREAD = "REPLY_ON_THREAD"
    RSC_WITHDRAWAL_COMPLETE = "RSC_WITHDRAWAL_COMPLETE"
    RSC_SUPPORT_ON_DOC = "RSC_SUPPORT_ON_DOC"
    RSC_SUPPORT_ON_DIS = "RSC_SUPPORT_ON_DIS"
    FLAGGED_CONTENT_VERDICT = "FLAGGED_CONTENT_VERDICT"
    BOUNTY_EXPIRING_SOON = "BOUNTY_EXPIRING_SOON"

    NOTIFICATION_TYPE_CHOICES = (
        (THREAD_ON_DOC, THREAD_ON_DOC),
        (COMMENT_ON_THREAD, COMMENT_ON_THREAD),
        (REPLY_ON_THREAD, REPLY_ON_THREAD),
        (RSC_WITHDRAWAL_COMPLETE, RSC_WITHDRAWAL_COMPLETE),
        (RSC_SUPPORT_ON_DOC, RSC_SUPPORT_ON_DOC),
        (RSC_SUPPORT_ON_DIS, RSC_SUPPORT_ON_DIS),
        (FLAGGED_CONTENT_VERDICT, FLAGGED_CONTENT_VERDICT),
        (BOUNTY_EXPIRING_SOON, BOUNTY_EXPIRING_SOON),
    )

    notification_type = models.CharField(max_length=32)

    body = ArrayField(
        HStoreField(), default=list  # Do not use [] because it is mutable and is shared
    )
    read = models.BooleanField(default=False)

    unified_document = models.ForeignKey(
        ResearchhubUnifiedDocument,
        null=True,
        on_delete=models.CASCADE,
        related_name="notifications",
    )

    # The user that should receive the notification
    recipient = models.ForeignKey(
        User,
        related_name="receiver_notifications",
        on_delete=models.CASCADE,
    )

    # The user that created the notifcation, e.g the user created a comment
    action_user = models.ForeignKey(
        User, related_name="creator_notifications", on_delete=models.CASCADE
    )
    action = models.ForeignKey(
        Action, related_name="notifications", on_delete=models.CASCADE
    )

    read_date = models.DateTimeField(null=True, blank=True)
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    def send_notification(self):
        user = self.recipient
        room = f"notification_{user.id}"
        notification_type = self.action.content_type.app_label
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            room,
            {
                "type": "send_notification",
                "notification_type": notification_type,
                "id": self.id,
            },
        )

    def _create_frontend_doc_link(self):
        base_url = self.unified_document.frontend_view_link()

    def format_body(self):
        recipient = self.recipient
        action_user = self.action_user

        action_user_name = f"{action_user.first_name} {action_user.last_name}"
        if self.notification_type == self.THREAD_ON_DOC:
            pass
