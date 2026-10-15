from django.db import transaction
from django.template.loader import render_to_string

from mailing_list.services import EMAIL_PREVIEW_LENGTH, EmailService
from notification.models import Notification
from notification.services import NotificationService
from researchhub_comment.models import RhCommentModel
from researchhub_comment.services.comment_html_service import render_comment_html
from researchhub_document.services.work_cover_service_for_email import build_work_cover
from user.models import User


def notify_mentioned_users(comment_id: int, recipient_ids: list[int]) -> None:
    """Create each new mention notice and email its recipient after commit."""
    comment = RhCommentModel.objects.select_related(
        "created_by__author_profile", "thread"
    ).get(id=comment_id)
    author = comment.created_by
    unified_document = comment.thread.unified_document
    notifications = NotificationService()
    emails = EmailService()
    subject = f"{author.full_name()} Mentioned You in a Comment"
    body = (
        ""
        if comment.thread.permissions.exists()
        else render_comment_html(comment, max_length=EMAIL_PREVIEW_LENGTH)
    )
    cover = build_work_cover(comment.thread.content_object)
    message = render_to_string(
        "email_activity_card.html",
        {
            "author": author.author_profile,
            "action": f"Commented on {cover['noun']}",
            "created_date": comment.created_date,
            "body": body,
            "cover": cover,
        },
    )
    link = comment.get_frontend_view_link()

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
            transaction.on_commit(
                lambda email=recipient.email: emails.send_message_email(
                    [email], subject, message, link=link, is_html=True
                ),
                robust=True,
            )
