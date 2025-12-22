from celery.utils.log import get_task_logger
from django.apps import apps

from paper.services.bedrock_embedding_service import BedrockEmbeddingService
from researchhub.celery import QUEUE_PAPER_MISC, app
from utils import sentry

logger = get_task_logger(__name__)


@app.task(queue=QUEUE_PAPER_MISC, bind=True)
def generate_paper_embedding(self, paper_id, retry=0):
    """
    Generate and store an embedding for a paper using its title and abstract.

    This task calls Amazon Bedrock's Titan Text Embeddings V2 model to generate
    a 1024-dimensional embedding vector that captures the semantic meaning of
    the paper's title and abstract.

    Args:
        paper_id: The ID of the paper to generate an embedding for.
        retry: Current retry count (max 2 retries).

    Returns:
        True if embedding was generated successfully, False otherwise.
    """
    if retry > 2:
        logger.warning(
            f"Max retries reached for embedding generation - paper {paper_id}"
        )
        return False

    Paper = apps.get_model("paper.Paper")

    try:
        paper = Paper.objects.get(id=paper_id)
    except Paper.DoesNotExist:
        logger.warning(f"Paper {paper_id} not found")
        return False

    # Get the title (prefer paper_title, fallback to title)
    title = paper.paper_title or paper.title
    if not title:
        logger.warning(f"Paper {paper_id} has no title, skipping embedding generation")
        return False

    abstract = paper.abstract

    try:
        service = BedrockEmbeddingService()
        embedding = service.generate_paper_embedding(title=title, abstract=abstract)

        if embedding is None:
            logger.warning(f"Failed to generate embedding for paper {paper_id}")
            # Retry
            if retry < 2:
                generate_paper_embedding.apply_async(
                    (paper_id, retry + 1),
                    priority=6,
                    countdown=60 * (retry + 1),
                )
            return False

        # Store the embedding
        paper.title_abstract_embedding = embedding
        paper.save(update_fields=["title_abstract_embedding"])

        logger.info(
            f"Generated embedding for paper {paper_id} "
            f"({len(embedding)} dimensions)"
        )
        return True

    except Exception as e:
        logger.error(f"Error generating embedding for paper {paper_id}: {e}")
        sentry.log_error(e)

        # Retry on failure
        if retry < 2:
            generate_paper_embedding.apply_async(
                (paper_id, retry + 1),
                priority=6,
                countdown=60 * (retry + 1),
            )

        return False


@app.task(queue=QUEUE_PAPER_MISC)
def generate_embeddings_batch(paper_ids, skip_existing=True):
    """
    Generate embeddings for a batch of papers.

    This task is useful for backfilling embeddings for existing papers.

    Args:
        paper_ids: List of paper IDs to generate embeddings for.
        skip_existing: If True, skip papers that already have embeddings.

    Returns:
        Dictionary with counts of processed, success, skipped, and failed papers.
    """
    Paper = apps.get_model("paper.Paper")

    results = {
        "processed": 0,
        "success": 0,
        "skipped": 0,
        "failed": 0,
    }

    for paper_id in paper_ids:
        results["processed"] += 1

        try:
            paper = Paper.objects.get(id=paper_id)
        except Paper.DoesNotExist:
            logger.warning(f"Paper {paper_id} not found, skipping")
            results["failed"] += 1
            continue

        # Skip if already has embedding
        if skip_existing and paper.title_abstract_embedding:
            logger.debug(f"Paper {paper_id} already has embedding, skipping")
            results["skipped"] += 1
            continue

        # Get title
        title = paper.paper_title or paper.title
        if not title:
            logger.warning(f"Paper {paper_id} has no title, skipping")
            results["failed"] += 1
            continue

        try:
            service = BedrockEmbeddingService()
            embedding = service.generate_paper_embedding(
                title=title, abstract=paper.abstract
            )

            if embedding:
                paper.title_abstract_embedding = embedding
                paper.save(update_fields=["title_abstract_embedding"])
                results["success"] += 1
                logger.info(f"Generated embedding for paper {paper_id}")
            else:
                results["failed"] += 1
                logger.warning(f"Failed to generate embedding for paper {paper_id}")

        except Exception as e:
            results["failed"] += 1
            logger.error(f"Error generating embedding for paper {paper_id}: {e}")
            sentry.log_error(e)

    logger.info(
        f"Batch embedding complete: {results['success']}/{results['processed']} "
        f"succeeded, {results['skipped']} skipped, {results['failed']} failed"
    )

    return results
