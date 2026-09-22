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
    # The comment model imports this task module before its class is defined.
    from researchhub_comment.services.comment_notification_service import (
        notify_mentioned_users,
    )

    notify_mentioned_users(comment_id, recipients)
