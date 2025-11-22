from celery.utils.log import get_task_logger

from analytics.interactions.interaction_mapper import map_from_upvote
from analytics.models import UserInteractions
from discussion.models import Vote
from paper.models import Paper
from personalize.services.sync_service import SyncService
from researchhub.celery import QUEUE_PAPER_MISC, app

logger = get_task_logger(__name__)


@app.task(queue=QUEUE_PAPER_MISC, max_retries=3, retry_backoff=True)
def create_upvote_interaction_task(vote_id):
    try:
        vote = Vote.objects.get(id=vote_id)
    except Vote.DoesNotExist:
        logger.error(f"Vote {vote_id} not found for UserInteraction creation")
        return

    if vote.vote_type != Vote.UPVOTE:
        logger.debug(
            f"Vote {vote_id} is not an UPVOTE (vote_type={vote.vote_type}), "
            f"skipping UserInteraction creation"
        )
        return

    if not vote.created_by_id:
        logger.warning(
            f"Vote {vote_id} has no created_by user, skipping UserInteraction creation"
        )
        return

    try:
        unified_doc = vote.unified_document
    except Exception as e:
        logger.warning(
            f"Vote {vote_id} has no valid unified_document: {str(e)}, "
            f"skipping UserInteraction creation"
        )
        return

    if not unified_doc:
        logger.warning(
            f"Vote {vote_id} has None unified_document, "
            f"skipping UserInteraction creation"
        )
        return

    try:
        interaction = map_from_upvote(vote)

        # UPVOTE has strict uniqueness constraint
        lookup_kwargs = {
            "user": interaction.user,
            "event": interaction.event,
            "unified_document": interaction.unified_document,
            "content_type": interaction.content_type,
            "object_id": interaction.object_id,
            "external_user_id__isnull": True,
        }

        interaction, was_created = UserInteractions.objects.get_or_create(
            **lookup_kwargs,
            defaults={
                "user": interaction.user,
                "external_user_id": None,
                "event": interaction.event,
                "unified_document": interaction.unified_document,
                "content_type": interaction.content_type,
                "object_id": interaction.object_id,
                "event_timestamp": interaction.event_timestamp,
                "is_synced_with_personalize": False,
                "personalize_rec_id": None,
            },
        )

        if was_created:
            logger.info(
                f"Created UserInteraction for UPVOTE: vote_id={vote_id}, "
                f"interaction_id={interaction.id}, user_id={vote.created_by_id}"
            )
        else:
            logger.debug(
                f"UserInteraction already exists for UPVOTE: vote_id={vote_id}, "
                f"interaction_id={interaction.id}, user_id={vote.created_by_id}"
            )

    except Exception as e:
        logger.error(
            f"Exception creating UserInteraction from UPVOTE: vote_id={vote_id}, "
            f"error={str(e)}",
            exc_info=True,
        )
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
def sync_paper_to_personalize_task(paper_id):
    try:
        paper = Paper.objects.get(id=paper_id)
    except Paper.DoesNotExist:
        logger.error(f"Paper {paper_id} not found for Personalize sync")
        return

    unified_doc = paper.unified_document

    if not unified_doc:
        logger.warning(
            f"Paper {paper_id} has no unified_document, skipping Personalize sync"
        )
        return

    logger.info(
        f"Syncing paper {paper_id} to Personalize (unified_doc: {unified_doc.id})"
    )

    try:
        personalize_sync_service = SyncService()
        result = personalize_sync_service.sync_item(unified_doc)

        if result["success"]:
            logger.info(
                f"Successfully synced paper {paper_id} to Personalize: {result}"
            )
        else:
            logger.error(f"Failed to sync paper {paper_id} to Personalize: {result}")
            raise Exception(f"Sync failed: {result}")

    except Exception as e:
        logger.error(
            f"Exception syncing paper {paper_id} to Personalize: {str(e)}",
            exc_info=True,
        )
        raise
