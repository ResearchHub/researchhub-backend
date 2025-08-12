import json
import logging

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile

from mailing_list.lib import base_email_context
from researchhub.celery import QUEUE_NOTIFICATION, app
from utils.message import send_email_message

logger = logging.getLogger(__name__)


@app.task()
def celery_create_comment_content_src(comment_id, comment_content):
    RhCommentModel = apps.get_model("researchhub_comment.RhCommentModel")

    rh_comment = RhCommentModel.objects.get(id=comment_id)
    thread = rh_comment.thread
    user = rh_comment.created_by
    comment_content_src_file = ContentFile(json.dumps(comment_content).encode("utf8"))
    rh_comment.comment_content_src.save(
        f"RH-THREAD-{thread.id}-COMMENT-{rh_comment.id}-user-{user.id}.txt",
        comment_content_src_file,
    )


@app.task(queue=QUEUE_NOTIFICATION)
def celery_create_mention_notification(comment_id, recipients):
    RhCommentModel = apps.get_model("researchhub_comment.RhCommentModel")
    Notification = apps.get_model("notification.Notification")

    comment = RhCommentModel.objects.get(id=comment_id)
    thread = comment.thread

    unified_document = thread.unified_document
    for recipient in recipients:
        if (
            recipient
            and not Notification.objects.filter(
                object_id=comment.id,
                content_type=ContentType.objects.get_for_model(RhCommentModel),
                recipient_id=recipient,
                action_user=comment.created_by,
                notification_type=Notification.COMMENT_USER_MENTION,
            ).exists()
        ):
            comment_created_by = comment.created_by
            notification = Notification.objects.create(
                item=comment,
                action_user=comment_created_by,
                recipient_id=recipient,
                unified_document=unified_document,
                notification_type=Notification.COMMENT_USER_MENTION,
            )
            notification.send_notification()

            outer_subject = "You were Mentioned in a Comment"
            context = {**base_email_context}
            context["action"] = {
                "message": f"{comment_created_by.first_name} {comment_created_by.last_name} has you mention in their comment",
                "frontend_view_link": f"{unified_document.frontend_view_link()}#comments",
            }
            context["subject"] = outer_subject
            send_email_message(
                [notification.recipient.email],
                "general_email_message.txt",
                outer_subject,
                context,
                html_template="general_email_message.html",
            )


@app.task(queue=QUEUE_NOTIFICATION)
def send_author_update_email_notifications(comment_id, follower_user_ids):
    """
    Send email notifications to followers about preregistration author updates.
    This runs asynchronously to avoid blocking the main transaction.
    """
    RhCommentModel = apps.get_model("researchhub_comment.RhCommentModel")
    User = apps.get_model("user.User")

    try:
        comment = RhCommentModel.objects.get(id=comment_id)
        document = comment.unified_document.get_document()
        author = comment.created_by

        context = {**base_email_context}
        context["action"] = {
            "message": f"{author.first_name} {author.last_name} posted an update to a preregistration you're following",
            "frontend_view_link": comment.unified_document.frontend_view_link(),
        }
        context["document_title"] = document.title
        context["author_name"] = author.full_name()

        subject = "Update on Preregistration You're Following"

        for user_id in follower_user_ids:
            try:
                user = User.objects.get(id=user_id)
                # Check if user wants to receive emails (following existing patterns)
                email_recipient = getattr(user, "emailrecipient", None)
                if email_recipient and email_recipient.receives_notifications:
                    send_email_message(
                        [user.email],
                        "general_email_message.txt",
                        subject,
                        context,
                        html_template="general_email_message.html",
                    )
            except Exception as e:
                # Log individual user failures but continue with others
                logger.error(
                    f"Failed to send author update email to user {user_id}: {e}"
                )

    except Exception as e:
        logger.error(
            f"Failed to send author update emails for comment {comment_id}: {e}"
        )
