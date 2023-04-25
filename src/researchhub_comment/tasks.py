import json

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile

from mailing_list.lib import base_email_context
from researchhub.celery import QUEUE_NOTIFICATION, app
from utils.message import send_email_message


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
    unified_document = comment.unified_document
    for recipient in recipients:
        if not Notification.objects.filter(
            object_id=comment.id,
            content_type=ContentType.objects.get_for_model(RhCommentModel),
            recipient_id=recipient,
            action_user=comment.created_by,
            notification_type=Notification.COMMENT_USER_MENTION,
        ).exists():
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
