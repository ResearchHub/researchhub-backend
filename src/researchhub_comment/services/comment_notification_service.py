from django.db import transaction

from mailing_list.services import EmailService
from notification.models import Notification
from notification.services import NotificationService
from researchhub_comment.models import RhCommentModel
from user.models import User


def notify_mentioned_users(comment_id: int, recipient_ids: list[int]) -> None:
    """Create each new mention notice and email its recipient after commit."""
    comment = RhCommentModel.objects.select_related("created_by", "thread").get(
        id=comment_id
    )
    author = comment.created_by
    unified_document = comment.thread.unified_document
    notifications = NotificationService()
    emails = EmailService()
    subject = "You were Mentioned in a Comment"
    message = f"{author.first_name} {author.last_name} mentioned you in their comment"

    for recipient in User.objects.filter(
        id__in=[recipient_id for recipient_id in recipient_ids if recipient_id]
    ):
        notification = notifications.send_once(
            Notification.COMMENT_USER_MENTION,
            recipient=recipient,
            action_user=author,
            item=comment,
            unified_document=unified_document,
        )
        if notification is not None:
            link = f"{unified_document.frontend_view_link()}#comments"
            transaction.on_commit(
                lambda email=recipient.email, link=link: emails.send_message_email(
                    [email], subject, message, link=link
                ),
                robust=True,
            )
