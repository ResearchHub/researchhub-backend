import json

from django.apps import apps
from django.core.files.base import ContentFile

from researchhub.celery import QUEUE_NOTIFICATION, app


@app.task()
def celery_create_comment_content_src(comment_id, comment_content):
    RhCommentModel = apps.get_model("researchhub_comment.RhCommentModel")  # noqa: N806

    rh_comment = RhCommentModel.objects.get(id=comment_id)
    thread = rh_comment.thread
    user = rh_comment.created_by
    comment_content_src_file = ContentFile(json.dumps(comment_content).encode("utf8"))
    rh_comment.comment_content_src.save(
        f"RH-THREAD-{thread.id}-COMMENT-{rh_comment.id}-user-{user.id}.txt",
        comment_content_src_file,
    )


@app.task(queue=QUEUE_NOTIFICATION)
def celery_create_mention_notification(comment_id: int, recipients: list[int]) -> None:
    """Notify each mentioned user about the comment, skipping duplicates."""
    # Imported here because notification.models pulls in the unified document
    # model, which imports this app's models, which import this module.
    from notification.models import Notification
    from notification.services import NotificationService
    from researchhub_comment.models import RhCommentModel
    from user.models import User

    comment = RhCommentModel.objects.select_related(
        "created_by", "thread__unified_document"
    ).get(id=comment_id)
    author = comment.created_by
    unified_document = comment.thread.unified_document
    notifications = NotificationService()

    for recipient in User.objects.filter(
        id__in=[recipient_id for recipient_id in recipients if recipient_id]
    ):
        notifications.send_once(
            Notification.COMMENT_USER_MENTION,
            recipient=recipient,
            action_user=author,
            item=comment,
            unified_document=unified_document,
            email_subject="You were Mentioned in a Comment",
            email_message=(
                f"{author.first_name} {author.last_name} mentioned you in their comment"
            ),
        )
