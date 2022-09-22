from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib.postgres.fields import ArrayField, HStoreField
from django.db import models

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
    DIS_ON_BOUNTY = "DIS_ON_BOUNTY"

    NOTIFICATION_TYPE_CHOICES = (
        (THREAD_ON_DOC, THREAD_ON_DOC),
        (COMMENT_ON_THREAD, COMMENT_ON_THREAD),
        (REPLY_ON_THREAD, REPLY_ON_THREAD),
        (RSC_WITHDRAWAL_COMPLETE, RSC_WITHDRAWAL_COMPLETE),
        (RSC_SUPPORT_ON_DOC, RSC_SUPPORT_ON_DOC),
        (RSC_SUPPORT_ON_DIS, RSC_SUPPORT_ON_DIS),
        (FLAGGED_CONTENT_VERDICT, FLAGGED_CONTENT_VERDICT),
        (BOUNTY_EXPIRING_SOON, BOUNTY_EXPIRING_SOON),
        (DIS_ON_BOUNTY, DIS_ON_BOUNTY),
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

    def format_body(self):
        format_func = getattr(
            self, f"_format_{self.notification_type.lower()}", lambda: []
        )
        self.body = format_func()

    def _create_frontend_doc_link(self):
        base_url = self.unified_document.frontend_view_link()
        return base_url

    def _format_thread_on_doc(self):
        document = self.unified_document.get_document()
        action_user = self.action_user
        action_user_name = action_user.first_name
        doc_title = document.title
        base_url = self._create_frontend_doc_link()

        return [
            {"type": "text", "value": action_user_name, "extra": ("bold",)},
            {"type": "text", "value": "created a"},
            {"type": "link", "value": "thread", "link": f"{base_url}#comments"},
            {"type": "text", "value": "in"},
            {"type": "link", "value": doc_title, "link": base_url},
        ]

    def _format_comment_on_thread(self):
        action = self.action
        action_user = self.action_user
        action_user_name = action_user.first_name
        base_url = self._create_frontend_doc_link()
        comment_plain_text = action.item.plain_text

        return [
            {"type": "text", "value": action_user_name, "extra": ("bold",)},
            {"type": "text", "value": "left a"},
            {"type": "link", "value": "comment", "link": f"{base_url}#comments"},
            {"type": "text", "value": "in your thread"},
            {"type": "link", "value": comment_plain_text, "link": base_url},
        ]

    def _format_reply_on_thread(self):
        action = self.action
        action_user = self.action_user
        action_user_name = action_user.first_name
        base_url = self._create_frontend_doc_link()
        reply_plain_text = action.item.plain_text

        return [
            {"type": "text", "value": action_user_name, "extra": ("bold",)},
            {"type": "text", "value": "left a"},
            {"type": "link", "value": "reply", "link": f"{base_url}#comments"},
            {"type": "text", "value": "in your comment"},
            {"type": "link", "value": reply_plain_text, "link": base_url},
        ]

    def _format_rsc_withdrawal_complete(self):
        action = self.action
        withdrawal = action.item
        rsc_amount = withdrawal.amount
        transaction_hash = withdrawal.transaction_hash
        url = f"https://rinkeby.etherscan.io/tx/{transaction_hash}"

        return [
            {
                "type": "text",
                "value": f"Your withdrawal of {rsc_amount} RSC has now been completed!\n",
            },
            {"type": "text", "value": "View the transaction at\n"},
            {"type": "link", "value": url, "link": url},
        ]

    def _format_rsc_support_on_doc(self):
        action = self.action
        document = self.unified_document.get_document()
        action_user = self.action_user
        action_user_name = action_user.first_name
        base_url = self._create_frontend_doc_link()
        purchase = action.item

        return [
            {"type": "text", "value": "Congratulations!🎉 Your"},
            {
                "type": "link",
                "value": f"{document.document_type.lower()}",
                "link": base_url,
            },
            {"type": "text", "value": f"has been awarded {purchase.amount} RSC by"},
            {"type": "text", "value": action_user_name, "extra": ("bold",)},
        ]

    def _format_rsc_support_on_dis(self):
        action = self.action
        action_user = self.action_user
        action_user_name = action_user.first_name
        base_url = self._create_frontend_doc_link()
        purchase = action.item
        dis = action.item.item

        return [
            {"type": "text", "value": "Congratulations!🎉 Your"},
            {
                "type": "link",
                "value": f"{dis._meta.model_name}",
                "link": f"{base_url}#comments",
            },
            {"type": "text", "value": f"has been awarded {purchase.amount} RSC by"},
            {"type": "text", "value": action_user_name, "extra": ("bold",)},
        ]

    def _format_flagged_content_verdict(self):
        action = self.action
        verdict = action.item
        flag = verdict.flag
        item = flag.item
        unified_document = item.unified_document
        doc_title = unified_document.get_document().title
        base_url = unified_document.frontend_view_link()

        return [
            {"type": "text", "value": "A ResearchHub Editor has removed your"},
            {
                "type": "text",
                "value": f"{item._meta.model_name} for {verdict.verdict_choice.lower()} in",
            },
            {"type": "link", "value": doc_title, "link": base_url},
        ]

    def _format_bounty_expiring_soon(self):
        action = self.action
        bounty = action.item
        unified_document = bounty.unified_document
        document = unified_document.get_document()
        doc_title = document.title
        base_url = unified_document.frontend_view_link()

        return [
            {"type": "text", "value": "Your bounty is expiring in"},
            {"type": "text", "value": "24 hours", "extra": ("bold",)},
            {"type": "text", "value": "Please award it to the best answer."},
            {"type": "link", "value": doc_title, "link": base_url},
        ]

    def _format_dis_on_bounty(self):
        action = self.action
        action_user = self.action_user
        action_user_name = action_user.first_name
        bounty = action.item
        bounty_item = bounty.item
        unified_document = bounty.unified_document
        base_url = unified_document.frontend_view_link()

        return [
            {"type": "text", "value": f"{action_user_name} left a"},
            {
                "type": "link",
                "value": f"{bounty_item._meta.model_name}",
                "link": f"{base_url}#comments",
            },
            {"type": "text", "value": "on your"},
            {"type": "link", "value": "bounty", "link": base_url},
        ]
