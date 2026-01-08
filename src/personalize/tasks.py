from celery.utils.log import get_task_logger

from analytics.interactions.interaction_mapper import (
    map_from_comment,
    map_from_list_item,
    map_from_upvote,
)
from analytics.models import UserInteractions
from discussion.models import Vote
from personalize.services.sync_service import SyncService
from researchhub.celery import QUEUE_PAPER_MISC, app
from researchhub_comment.models import RhCommentModel
from user_lists.models import ListItem
from utils.sentry import log_error

logger = get_task_logger(__name__)


@app.task(queue=QUEUE_PAPER_MISC, max_retries=3, retry_backoff=True)
def create_upvote_interaction_task(vote_id):
    try:
        vote = Vote.objects.get(id=vote_id)
    except Vote.DoesNotExist:
        logger.error(f"Vote {vote_id} not found")
        return

    if vote.vote_type != Vote.UPVOTE:
        return

    if not vote.created_by_id:
        logger.warning(f"Vote {vote_id} missing created_by_id")
        return

    try:
        unified_doc = vote.unified_document
    except Exception:
        return

    if not unified_doc:
        logger.warning(f"Vote {vote_id} missing unified_document")
        return

    # Skip self-upvotes
    if unified_doc.created_by and unified_doc.created_by.id == vote.created_by_id:
        return

    try:
        interaction = map_from_upvote(vote)
        UserInteractions.objects.get_or_create(
            user=interaction.user,
            event=interaction.event,
            unified_document=interaction.unified_document,
            content_type=interaction.content_type,
            object_id=interaction.object_id,
            defaults={"event_timestamp": interaction.event_timestamp},
        )
    except Exception as e:
        logger.error(f"Failed creating interaction for vote {vote_id}: {e}")
        raise


@app.task(queue=QUEUE_PAPER_MISC, max_retries=3, retry_backoff=True)
def create_comment_interaction_task(comment_id):
    try:
        comment = RhCommentModel.objects.get(id=comment_id)
    except RhCommentModel.DoesNotExist:
        logger.error(f"Comment {comment_id} not found")
        return

    if not comment.created_by_id:
        logger.warning(f"Comment {comment_id} missing created_by_id")
        return

    try:
        unified_doc = comment.unified_document
    except Exception:
        return

    if not unified_doc:
        logger.warning(f"Comment {comment_id} missing unified_document")
        return

    try:
        interaction = map_from_comment(comment)
        UserInteractions.objects.get_or_create(
            user=interaction.user,
            event=interaction.event,
            unified_document=interaction.unified_document,
            content_type=interaction.content_type,
            object_id=interaction.object_id,
            defaults={"event_timestamp": interaction.event_timestamp},
        )
    except Exception as e:
        log_error(e, message=f"Failed creating interaction for comment {comment_id}")
        raise


@app.task(queue=QUEUE_PAPER_MISC, max_retries=3, retry_backoff=True)
def create_list_item_interaction_task(list_item_id):
    try:
        list_item = ListItem.objects.get(id=list_item_id)
    except ListItem.DoesNotExist:
        logger.error(f"ListItem {list_item_id} not found")
        return

    try:
        interaction = map_from_list_item(list_item)
        UserInteractions.objects.get_or_create(
            user=interaction.user,
            event=interaction.event,
            unified_document=interaction.unified_document,
            content_type=interaction.content_type,
            object_id=interaction.object_id,
            defaults={"event_timestamp": interaction.event_timestamp},
        )
    except Exception as e:
        logger.error(f"Failed creating interaction for list item {list_item_id}: {e}")
        raise


@app.task(queue=QUEUE_PAPER_MISC, max_retries=3, retry_backoff=True)
def sync_interaction_event_to_personalize_task(interaction_id):
    try:
        interaction = UserInteractions.objects.get(id=interaction_id)
    except UserInteractions.DoesNotExist:
        logger.error(
            f"UserInteraction {interaction_id} not found for Personalize event sync"
        )
        return

    if not interaction.unified_document_id or (
        not interaction.user_id and not interaction.external_user_id
    ):
        logger.warning(
            f"UserInteraction {interaction_id} missing required fields, "
            f"skipping Personalize event sync"
        )
        return

    try:
        personalize_sync_service = SyncService()
        result = personalize_sync_service.sync_event(interaction)

        if result["success"]:
            interaction.is_synced_with_personalize = True
            interaction.save(update_fields=["is_synced_with_personalize"])
        else:
            raise Exception(f"Event sync failed: {result}")

    except Exception as e:
        logger.error(
            f"Exception syncing event to Personalize: "
            f"interaction_id={interaction_id}, error={str(e)}",
        )
        raise


@app.task(queue=QUEUE_PAPER_MISC, max_retries=3, retry_backoff=True)
def sync_unified_document_to_personalize_task(unified_document_id):
    """
    Sync a unified document to AWS Personalize.
    """
    logger.info(f"Syncing unified_document {unified_document_id} to Personalize")

    service = SyncService()
    result = service.sync_item_by_id(unified_document_id)

    if result["success"]:
        logger.info(
            f"Successfully synced unified_document {unified_document_id} "
            f"to Personalize: {result}"
        )
    else:
        raise Exception(f"Sync failed: {result}")
