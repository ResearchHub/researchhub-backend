import threading
import urllib.parse
from io import StringIO

from celery.utils.log import get_task_logger
from django.apps import apps
from django.conf import settings
from django.core.management import call_command

from paper.ingestion.pipeline import (  # noqa: F401
    fetch_all_papers,
    fetch_papers_from_source,
    process_batch_task,
)
from paper.ingestion.tasks import (  # noqa: F401
    enrich_paper_with_bluesky_metrics,
    enrich_paper_with_github_metrics,
    enrich_paper_with_x_metrics,
    enrich_papers_with_openalex,
    update_recent_papers_with_bluesky_metrics,
    update_recent_papers_with_github_metrics,
    update_recent_papers_with_x_metrics,
)
from paper.utils import download_pdf_from_url
from researchhub.celery import QUEUE_PAPER_MISC, app
from utils import sentry

logger = get_task_logger(__name__)

# Module-level cache for the embedding model
# This ensures the model is only loaded once per worker process
_embedding_model_cache = {}
_embedding_model_lock = threading.Lock()


def get_embedding_model(model_name=None, device=None):
    """
    Get or create a cached SentenceTransformer model instance.

    The model is cached at the module level to avoid reloading it
    for each task execution. This significantly improves performance.

    Args:
        model_name: Name of the model to load (defaults to settings)
        device: Device to use ('cpu' or 'cuda', defaults to settings)

    Returns:
        SentenceTransformer: Cached model instance
    """
    if model_name is None:
        model_name = getattr(settings, "ABSTRACT_VECTOR_MODEL", "all-MiniLM-L6-v2")
    if device is None:
        device = getattr(settings, "ABSTRACT_VECTOR_DEVICE", "cpu")

    cache_key = f"{model_name}_{device}"

    # Check if model is already cached
    if cache_key in _embedding_model_cache:
        return _embedding_model_cache[cache_key]

    # Load model with thread lock to prevent race conditions
    with _embedding_model_lock:
        # Double-check after acquiring lock
        if cache_key in _embedding_model_cache:
            return _embedding_model_cache[cache_key]

        try:
            from sentence_transformers import SentenceTransformer

            logger.info(f"Loading embedding model: {model_name} on {device}")
            model = SentenceTransformer(model_name, device=device)
            _embedding_model_cache[cache_key] = model
            logger.info(f"Successfully loaded and cached model: {model_name}")
            return model
        except ImportError:
            logger.error("sentence-transformers not installed")
            raise
        except Exception as e:
            logger.error(f"Failed to load model {model_name}: {str(e)}")
            raise


@app.task(queue=QUEUE_PAPER_MISC)
def censored_paper_cleanup(paper_id):
    Paper = apps.get_model("paper.Paper")
    paper = Paper.objects.filter(id=paper_id).first()

    if not paper.is_removed:
        paper.is_removed = True
        paper.save()

    if paper:
        paper.votes.update(is_removed=True)

        uploaded_by = paper.uploaded_by
        uploaded_by.set_probable_spammer()


@app.task(queue=QUEUE_PAPER_MISC)
def download_pdf(paper_id, retry=0):
    if retry > 3:
        return

    Paper = apps.get_model("paper.Paper")
    paper = Paper.objects.get(id=paper_id)

    pdf_url = paper.pdf_url or paper.url

    if pdf_url:
        try:
            url = create_download_url(pdf_url, paper.external_source)
            pdf = download_pdf_from_url(url)
            paper.file.save(pdf.name, pdf, save=False)
            paper.save(update_fields=["file"])

            return True
        except ValueError as e:
            logger.warning(f"No PDF at {url} - paper {paper_id}: {e}")
            sentry.log_info(f"No PDF at {url} - paper {paper_id}: {e}")
            return False
        except Exception as e:
            logger.warning(f"Failed to download PDF {url} - paper {paper_id}: {e}")
            sentry.log_info(f"Failed to download PDF {url} - paper {paper_id}: {e}")
            download_pdf.apply_async(
                (paper.id, retry + 1), priority=7, countdown=15 * (retry + 1)
            )
            return False

    return False


def create_download_url(url: str, external_source: str) -> str:
    if external_source not in ["arxiv", "biorxiv"]:
        return url

    scraper_url = settings.SCRAPER_URL
    if not scraper_url:
        return url

    target_url = urllib.parse.quote(url)
    return f"{scraper_url.format(url=target_url)}"


@app.task(queue=QUEUE_PAPER_MISC, bind=True, max_retries=2)
def generate_abstract_vector_for_paper(self, paper_id, skip_existing=True):
    """
    Generate abstract_fast_vector embedding for a single paper and update OpenSearch.

    This task is designed to be called after a paper is indexed to OpenSearch.
    It generates the vector embedding and updates the OpenSearch document.

    Args:
        paper_id: ID of the paper to generate vector for
        skip_existing: If True, skip if vector already exists in OpenSearch

    Returns:
        dict: Result with success status and details
    """
    try:
        Paper = apps.get_model("paper.Paper")
        paper = Paper.objects.get(id=paper_id)

        # Skip if paper doesn't have an abstract
        if not paper.abstract or paper.abstract.strip() == "":
            logger.debug(
                f"Paper {paper_id} has no abstract, skipping vector generation"
            )
            return {"success": False, "reason": "no_abstract"}

        # Get OpenSearch client
        from search.documents.paper import PaperDocument

        document = PaperDocument()
        client = document._index._get_connection()

        # Determine which index to use
        try:
            client.indices.get(index="paper_knn")
            index_name = "paper_knn"
        except Exception:
            index_name = PaperDocument._index._name

        # Check if vector already exists (if skip_existing is enabled)
        if skip_existing:
            try:
                doc = client.get(index=index_name, id=str(paper_id))
                source = doc.get("_source", {})
                existing_vector = source.get("abstract_fast_vector")
                if existing_vector and len(existing_vector) > 0:
                    logger.debug(
                        f"Paper {paper_id} already has abstract_fast_vector, skipping"
                    )
                    return {"success": False, "reason": "already_exists"}
            except Exception:
                # Document doesn't exist yet, continue processing
                pass

        # Check if document exists in OpenSearch, create if it doesn't (for paper_knn)
        try:
            client.get(index=index_name, id=str(paper_id))
        except Exception:
            # Document doesn't exist - if using paper_knn, create minimal document
            if index_name == "paper_knn":
                try:
                    # Create minimal document with just ID in paper_knn
                    client.index(
                        index=index_name,
                        id=str(paper_id),
                        body={"id": paper_id},
                    )
                    logger.info(
                        f"Created minimal document for paper {paper_id} "
                        f"in {index_name}"
                    )
                except Exception as create_error:
                    logger.warning(
                        f"Failed to create document for paper {paper_id} "
                        f"in {index_name}: {str(create_error)}"
                    )
                    return {"success": False, "reason": "failed_to_create_document"}
            else:
                logger.warning(
                    f"Paper {paper_id} not found in {index_name}, "
                    "skipping vector generation"
                )
                return {"success": False, "reason": "not_in_opensearch"}

        # Get model name and device from settings
        model_name = getattr(settings, "ABSTRACT_VECTOR_MODEL", "all-MiniLM-L6-v2")
        device = getattr(settings, "ABSTRACT_VECTOR_DEVICE", "cpu")

        # Get cached model (loads on first use, then reuses)
        try:
            model = get_embedding_model(model_name=model_name, device=device)
        except ImportError:
            logger.error(
                "sentence-transformers not installed, " "cannot generate vectors"
            )
            return {"success": False, "reason": "missing_dependency"}
        except Exception as e:
            logger.error(f"Failed to load embedding model: {str(e)}")
            sentry.log_error(e, message="Failed to load embedding model")
            return {"success": False, "reason": "model_load_failed"}

        # Truncate abstract if too long (most models handle ~4000 chars)
        abstract = paper.abstract[:4000]

        # Generate embedding using cached model
        embedding = model.encode(
            abstract, convert_to_numpy=True, show_progress_bar=False
        )
        embedding_list = embedding.tolist()

        # Update OpenSearch document
        client.update(
            index=index_name,
            id=str(paper_id),
            body={"doc": {"abstract_fast_vector": embedding_list}},
        )

        logger.info(f"Successfully generated and updated vector for paper {paper_id}")
        return {"success": True, "paper_id": paper_id, "model": model_name}

    except Paper.DoesNotExist:
        logger.warning(f"Paper {paper_id} not found in database")
        return {"success": False, "reason": "paper_not_found"}
    except Exception as e:
        logger.error(f"Failed to generate vector for paper {paper_id}: {str(e)}")
        sentry.log_error(e, message=f"Failed to generate vector for paper {paper_id}")
        # Retry once with exponential backoff
        raise self.retry(exc=e, countdown=60 * (self.request.retries + 1))


@app.task(queue=QUEUE_PAPER_MISC, bind=True, max_retries=3)
def generate_abstract_vectors_task(
    self,
    days=None,
    paper_ids=None,
    batch_size=50,
    skip_existing=False,
    model="all-MiniLM-L6-v2",
    device="cpu",
    index_name=None,
    dry_run=False,
):
    """
    Celery task to generate abstract_fast_vector embeddings for papers.

    Args:
        days: Number of days back from today to generate vectors for
        paper_ids: Comma-separated string of paper IDs (e.g., "123,456,789")
        batch_size: Number of papers to process in each batch
        skip_existing: Skip papers that already have abstract_fast_vector populated
        model: Sentence transformer model to use
        device: Device to use for inference ('cpu' or 'cuda')
        index_name: OpenSearch index name (optional)
        dry_run: Run without actually updating OpenSearch

    Returns:
        dict: Summary of processing results
    """
    try:
        # Capture command output
        out = StringIO()
        err = StringIO()

        # Build command arguments
        kwargs = {}
        if days is not None:
            kwargs["days"] = days
        if paper_ids:
            kwargs["paper_ids"] = paper_ids
        if batch_size:
            kwargs["batch_size"] = batch_size
        if skip_existing:
            kwargs["skip_existing"] = True
        if model:
            kwargs["model"] = model
        if device:
            kwargs["device"] = device
        if index_name:
            kwargs["index_name"] = index_name
        if dry_run:
            kwargs["dry_run"] = True

        # Call the management command
        call_command("generate_abstract_vectors", stdout=out, stderr=err, **kwargs)

        output = out.getvalue()
        error_output = err.getvalue()

        if error_output:
            logger.warning(f"Command stderr: {error_output}")

        logger.info(f"Abstract vector generation completed. Output: {output}")
        return {"success": True, "output": output, "error": error_output}

    except Exception as e:
        logger.error(f"Failed to generate abstract vectors: {str(e)}")
        sentry.log_error(e, message="Failed to generate abstract vectors")
        # Retry the task
        raise self.retry(exc=e, countdown=60 * (self.request.retries + 1))
