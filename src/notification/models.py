from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.fields import ArrayField, HStoreField
from django.db import models

from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.models import User


class Notification(models.Model):
    DEPRECATED = "DEPRECATED"
    COMMENT = "COMMENT"
    COMMENT_ON_COMMENT = "COMMENT_ON_COMMENT"
    COMMENT_USER_MENTION = "COMMENT_USER_MENTION"
    THREAD_ON_DOC = "THREAD_ON_DOC"
    COMMENT_ON_THREAD = "COMMENT_ON_THREAD"
    REPLY_ON_THREAD = "REPLY_ON_THREAD"
    RSC_WITHDRAWAL_COMPLETE = "RSC_WITHDRAWAL_COMPLETE"
    RSC_SUPPORT_ON_DOC = "RSC_SUPPORT_ON_DOC"
    RSC_SUPPORT_ON_DIS = "RSC_SUPPORT_ON_DIS"
    FLAGGED_CONTENT_VERDICT = "FLAGGED_CONTENT_VERDICT"
    BOUNTY_EXPIRING_SOON = "BOUNTY_EXPIRING_SOON"
    BOUNTY_HUB_EXPIRING_SOON = "BOUNTY_HUB_EXPIRING_SOON"
    DIS_ON_BOUNTY = "DIS_ON_BOUNTY"
    BOUNTY_PAYOUT = "BOUNTY_PAYOUT"
    PAPER_CLAIMED = "PAPER_CLAIMED"
    ACCOUNT_VERIFIED = "ACCOUNT_VERIFIED"
    FUNDRAISE_PAYOUT = "FUNDRAISE_PAYOUT"

    NOTIFICATION_TYPE_CHOICES = (
        (DEPRECATED, DEPRECATED),
        (RSC_WITHDRAWAL_COMPLETE, RSC_WITHDRAWAL_COMPLETE),
        (RSC_SUPPORT_ON_DOC, RSC_SUPPORT_ON_DOC),
        (RSC_SUPPORT_ON_DIS, RSC_SUPPORT_ON_DIS),
        (FLAGGED_CONTENT_VERDICT, FLAGGED_CONTENT_VERDICT),
        (BOUNTY_EXPIRING_SOON, BOUNTY_EXPIRING_SOON),
        (DIS_ON_BOUNTY, DIS_ON_BOUNTY),
        (COMMENT, COMMENT),
        (COMMENT_ON_COMMENT, COMMENT_ON_COMMENT),
        (COMMENT_USER_MENTION, COMMENT_USER_MENTION),
        (BOUNTY_PAYOUT, BOUNTY_PAYOUT),
        (ACCOUNT_VERIFIED, ACCOUNT_VERIFIED),
        (PAPER_CLAIMED, PAPER_CLAIMED),
        (FUNDRAISE_PAYOUT, FUNDRAISE_PAYOUT),
    )

    notification_type = models.CharField(
        choices=NOTIFICATION_TYPE_CHOICES, max_length=32, null=True
    )

    body = ArrayField(
        HStoreField(), default=list  # Do not use [] because it is mutable and is shared
    )
    extra = HStoreField(default=dict)
    navigation_url = models.URLField(null=True, max_length=1024)
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
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    item = GenericForeignKey(
        "content_type",
        "object_id",
    )

    read_date = models.DateTimeField(null=True, blank=True)
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = (models.Index(fields=("content_type", "object_id")),)

    def save(self, *args, **kwargs):
        self.format_body()
        super().save(*args, **kwargs)

    def send_notification(self):
        from notification.serializers import DynamicNotificationSerializer
        from notification.views import NotificationViewSet

        context = NotificationViewSet()._get_context()
        notification = Notification.objects.get(id=self.id)
        serialized_data = DynamicNotificationSerializer(
            notification,
            _include_fields=[
                "action_user",
                "body",
                "created_date",
                "id",
                "notification_type",
                "read",
                "read_date",
                "recipient",
            ],
            context=context,
        ).data

        user = self.recipient
        room = f"notification_{user.id}"
        notification_type = self.notification_type
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            room,
            {
                "type": "send_notification",
                "notification_type": notification_type,
                "data": serialized_data,
            },
        )

    def format_body(self):
        format_func = getattr(
            self, f"_format_{self.notification_type.lower()}", lambda: ([], None)
        )

        body, navigation_url = format_func()

        if len(body):
            self.body = body

        if navigation_url:
            self.navigation_url = navigation_url
