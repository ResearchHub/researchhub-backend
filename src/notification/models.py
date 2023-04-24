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

    def _truncate_title(self, title):
        if len(title) > 75:
            title = f"{title[:75]}..."
        return title

    def _create_frontend_doc_link(self):
        base_url = self.unified_document.frontend_view_link()
        return base_url

    def _format_thread_on_doc(self):
        document = self.unified_document.get_document()
        action_user = self.action_user
        action_user_name = action_user.first_name
        doc_title = self._truncate_title(document.title)
        base_url = self._create_frontend_doc_link()
        comments_url = f"{base_url}#comments"

        return [
            {
                "type": "link",
                "value": f"{action_user_name}",
                "extra": '["bold", "link"]',
                "link": action_user.frontend_view_link(),
            },
            {"type": "text", "value": "created a "},
            {
                "type": "link",
                "value": "thread ",
                "link": comments_url,
                "extra": '["link"]',
            },
            {"type": "text", "value": "in "},
            {"type": "link", "value": doc_title, "link": base_url, "extra": '["link"]'},
        ], comments_url

    def _format_comment_on_thread(self):
        item = self.item
        action_user = self.action_user
        action_user_name = action_user.first_name
        base_url = self._create_frontend_doc_link()
        comments_url = f"{base_url}#comments"
        comment_plain_text = item.plain_text

        return [
            {
                "type": "link",
                "value": f"{action_user_name}",
                "extra": '["bold", "link"]',
                "link": action_user.frontend_view_link(),
            },
            {"type": "text", "value": "left a "},
            {
                "type": "link",
                "value": "comment ",
                "link": comments_url,
                "extra": '["link"]',
            },
            {"type": "text", "value": "in your thread "},
            {
                "type": "link",
                "value": comment_plain_text,
                "link": base_url,
                "extra": '["link"]',
            },
        ], comments_url

    def _format_reply_on_thread(self):
        item = self.item
        action_user = self.action_user
        action_user_name = action_user.first_name
        base_url = self._create_frontend_doc_link()
        comments_url = f"{base_url}#comments"
        reply_plain_text = item.plain_text

        return [
            {
                "type": "link",
                "value": f"{action_user_name}",
                "extra": '["bold", "link"]',
                "link": action_user.frontend_view_link(),
            },
            {"type": "text", "value": "left a "},
            {
                "type": "link",
                "value": "reply ",
                "link": comments_url,
                "extra": '["link"]',
            },
            {"type": "text", "value": "in your comment "},
            {
                "type": "link",
                "value": reply_plain_text,
                "link": base_url,
                "extra": '["link"]',
            },
        ], comments_url

    def _format_rsc_withdrawal_complete(self):
        withdrawal = self.item
        rsc_amount = withdrawal.amount
        transaction_hash = withdrawal.transaction_hash
        url = f"https://rinkeby.etherscan.io/tx/{transaction_hash}"

        return [
            {
                "type": "text",
                "value": "Your withdrawal of ",
            },
            {
                "type": "text",
                "value": f"{rsc_amount} RSC",
                "extra": '["bold"]',
            },
            {
                "type": "text",
                "value": "has now been completed!\n",
            },
            {"type": "text", "value": "View the transaction at\n"},
            {"type": "link", "value": url, "link": url, "extra": '["link"]'},
        ], None

    def _format_rsc_support_on_doc(self):
        purchase = self.item
        unified_document = self.unified_document
        action_user = self.action_user
        action_user_name = action_user.first_name
        base_url = self._create_frontend_doc_link()

        return [
            {"type": "text", "value": "Congratulations! 🎉 Your "},
            {
                "type": "link",
                "value": f"{unified_document.document_type.lower()} ",
                "link": base_url,
                "extra": '["link"]',
            },
            {"type": "text", "value": f"has been awarded {purchase.amount} RSC by "},
            {
                "type": "link",
                "value": action_user_name,
                "extra": '["bold", "link"]',
                "link": action_user.frontend_view_link(),
            },
        ], base_url

    def _format_rsc_support_on_dis(self):
        purchase = self.item
        action_user = self.action_user
        action_user_name = action_user.first_name
        base_url = self._create_frontend_doc_link()
        comments_url = f"{base_url}#comments"

        return [
            {"type": "text", "value": "Congratulations! 🎉 Your "},
            {
                "type": "link",
                "value": "comment ",
                "link": comments_url,
                "extra": '["link"]',
            },
            {"type": "text", "value": f"has been awarded {purchase.amount} RSC by "},
            {
                "type": "link",
                "value": action_user_name,
                "extra": '["bold", "link"]',
                "link": action_user.frontend_view_link(),
            },
        ], comments_url

    def _format_flagged_content_verdict(self):
        verdict = self.item
        flag = verdict.flag
        item = flag.item
        unified_document = item.unified_document
        doc_title = self._truncate_title(unified_document.get_document().title)
        base_url = unified_document.frontend_view_link()

        return [
            {"type": "text", "value": "A ResearchHub Editor has removed your "},
            {
                "type": "text",
                "value": f"{item._meta.model_name} for {verdict.verdict_choice.lower()} in ",
            },
            {"type": "link", "value": doc_title, "link": base_url, "extra": '["link"]'},
        ], None

    def _format_bounty_expiring_soon(self):
        bounty = self.item
        unified_document = bounty.unified_document
        document = unified_document.get_document()
        doc_title = self._truncate_title(document.title)
        base_url = unified_document.frontend_view_link()

        return [
            {"type": "text", "value": "Your bounty is expiring in "},
            {"type": "text", "value": "24 hours. ", "extra": '["bold"]'},
            {"type": "text", "value": "Please award it to the best answer. "},
            {"type": "link", "value": doc_title, "link": base_url, "extra": '["link"]'},
        ], base_url

    def _format_bounty_hub_expiring_soon(self):
        bounty = self.item
        unified_document = bounty.unified_document
        document = unified_document.get_document()
        doc_title = self._truncate_title(document.title)
        base_url = unified_document.frontend_view_link()

        return [
            {"type": "text", "value": "A "},
            {
                "type": "text",
                "value": f"{bounty.amount:.0f} RSC ",
                "extra": '["bold", "rsc_color"]',
            },
            {"type": "text", "value": "bounty for "},
            {
                "type": "link",
                "value": f"{doc_title} ",
                "link": base_url,
                "extra": '["link"]',
            },
            {"type": "text", "value": "is expiring soon. "},
            {
                "type": "text",
                "value": "Answer before the bounty expires!",
            },
        ], base_url

    def _format_dis_on_bounty(self):
        bounty = self.item
        action_user = self.action_user
        action_user_name = action_user.first_name
        bounty_item = bounty.item
        unified_document = bounty.unified_document
        base_url = unified_document.frontend_view_link()
        comments_url = f"{base_url}#comments"

        return [
            {
                "type": "link",
                "value": f"{action_user_name}",
                "extra": '["bold", "link"]',
                "link": action_user.frontend_view_link(),
            },
            {"type": "text", "value": "left a "},
            {
                "type": "link",
                "value": f"{bounty_item._meta.model_name} ",
                "link": comments_url,
                "extra": '["link"]',
            },
            {"type": "text", "value": "on your "},
            {"type": "link", "value": "bounty", "link": base_url, "extra": '["link"]'},
        ], comments_url

    def _format_comment(self):
        document = self.unified_document.get_document()
        action_user = self.action_user
        action_user_name = action_user.first_name
        doc_title = self._truncate_title(document.title)
        base_url = self._create_frontend_doc_link()
        comments_url = f"{base_url}/#comments"

        return [
            {
                "type": "link",
                "value": f"{action_user_name}",
                "extra": '["bold", "link"]',
                "link": action_user.frontend_view_link(),
            },
            {"type": "text", "value": "created a "},
            {
                "type": "link",
                "value": "thread ",
                "link": comments_url,
                "extra": '["link"]',
            },
            {"type": "text", "value": "in "},
            {"type": "link", "value": doc_title, "link": base_url, "extra": '["link"]'},
        ], comments_url

    def _format_comment_on_comment(self):
        item = self.item
        action_user = self.action_user
        action_user_name = action_user.first_name
        base_url = self._create_frontend_doc_link()
        comments_url = f"{base_url}#comments"
        comment_plain_text = item.plain_text

        return [
            {
                "type": "link",
                "value": f"{action_user_name}",
                "extra": '["bold", "link"]',
                "link": action_user.frontend_view_link(),
            },
            {"type": "text", "value": "left a "},
            {
                "type": "link",
                "value": "reply ",
                "link": comments_url,
                "extra": '["link"]',
            },
            {"type": "text", "value": "to your comment "},
            {
                "type": "link",
                "value": comment_plain_text,
                "link": base_url,
                "extra": '["link"]',
            },
        ], comments_url

    def _format_comment_user_mention(self):
        action_user = self.action_user
        action_user_name = action_user.first_name
        base_url = self._create_frontend_doc_link()
        comments_url = f"{base_url}#comments"

        return [
            {
                "type": "link",
                "value": f"{action_user_name}",
                "extra": '["bold", "link"]',
                "link": action_user.frontend_view_link(),
            },
            {"type": "text", "value": "has mentioned you in a "},
            {
                "type": "link",
                "value": "comment ",
                "link": comments_url,
                "extra": '["link"]',
            },
        ], comments_url

    def _format_bounty_payout(self):
        unified_document = self.unified_document
        action_user = self.action_user
        action_user_name = action_user.first_name
        document = unified_document.get_document()
        doc_title = self._truncate_title(title=document.title)
        base_url = unified_document.frontend_view_link()
        comments_url = f"{base_url}#comments"

        return [
            {
                "type": "link",
                "value": f"{action_user_name}",
                "extra": '["bold", "link"]',
                "link": action_user.frontend_view_link(),
            },
            {
                "type": "text",
                "value": "awarded you RSC for your ",
            },
            {
                "type": "link",
                "value": "thread ",
                "link": comments_url,
                "extra": '["link"]',
            },
            {"type": "text", "value": "in "},
            {
                "type": "link",
                "value": doc_title,
                "link": base_url,
                "extra": '["link"]',
            },
        ], comments_url
