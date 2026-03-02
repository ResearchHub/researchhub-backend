import json
import logging

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.core.files.base import ContentFile
from django.db.models import Q
from django.utils import timezone

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


def _calculate_and_save_score(comment, scorer=None):
    """Helper function to calculate and save academic score for a comment."""
    from researchhub_comment.scoring import CommentScorer
    
    if scorer is None:
        scorer = CommentScorer()
    
    context = {
        'tip_amount': comment.tip_amount,
        'bounty_award_amount': comment.bounty_award_amount,
        'is_verified_user': comment.is_verified_user
    }
    
    score_data = scorer.calculate_score(comment, context)
    
    comment.cached_academic_score = score_data["score"]
    comment.score_last_calculated = timezone.now()
    comment.save(update_fields=['cached_academic_score', 'score_last_calculated'])
    
    return score_data["score"]


def _get_stale_comments(hours_old=1, batch_size=500, user_id=None):
    """Get comments that need score recalculation."""
    from datetime import timedelta
    
    RhCommentModel = apps.get_model("researchhub_comment.RhCommentModel")
    
    threshold = timezone.now() - timedelta(hours=hours_old)
    queryset = RhCommentModel.objects.filter(
        Q(score_last_calculated__isnull=True) | 
        Q(score_last_calculated__lt=threshold)
    )
    
    if user_id:
        queryset = queryset.filter(created_by_id=user_id)
    
    return queryset.with_academic_scores().select_related(
        'created_by', 'created_by__userverification'
    )[:batch_size]


@app.task(max_retries=3, default_retry_delay=60)
def update_comment_academic_score(comment_id):
    """Update academic score for a single comment."""
    RhCommentModel = apps.get_model("researchhub_comment.RhCommentModel")
    
    try:
        comment = RhCommentModel.objects.with_academic_scores().select_related(
            'created_by', 'created_by__userverification'
        ).get(id=comment_id)
        
        score = _calculate_and_save_score(comment)
        logger.info(f"Updated academic score for comment {comment_id}: {score}")
        return score
        
    except RhCommentModel.DoesNotExist:
        logger.warning(f"Comment {comment_id} not found for score update")
        return None
    except Exception as e:
        logger.error(f"Failed to update score for comment {comment_id}: {e}")
        raise update_comment_academic_score.retry(exc=e)


@app.task()
def check_stale_comment_scores(hours_old=1, batch_size=500, user_id=None):
    """
    Check and update academic scores for stale comments.
    Pattern matches check_open_bounties - single task with helper functions.
    """
    from researchhub_comment.scoring import CommentScorer
    
    RhCommentModel = apps.get_model("researchhub_comment.RhCommentModel")
    
    # Get stale comments
    stale_comments = _get_stale_comments(hours_old, batch_size, user_id)
    
    # Process them
    scorer = CommentScorer()
    updated_count = 0
    failed_count = 0
    updates = []
    
    with transaction.atomic():
        for comment in stale_comments.iterator(chunk_size=100):
            try:
                _calculate_and_save_score(comment)
                updated_count += 1
            except Exception as e:
                logger.error(f"Failed to update score for comment {comment.id}: {e}")
                failed_count += 1
    
    logger.info(f"Updated {updated_count} comment scores, {failed_count} failures")
    return f"Updated {updated_count} comments, {failed_count} failures"

