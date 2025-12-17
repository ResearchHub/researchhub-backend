import logging

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils.crypto import get_random_string
from django.utils.text import slugify

from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import (
    PAPER as PAPER_DOC_TYPE,
)
from utils.doi import DOI
from utils.sentry import log_error, log_info

from .models import Paper
from .related_models.paper_version import PaperVersion

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Paper, dispatch_uid="add_paper_slug")
def add_paper_slug(sender, instance, created, update_fields, **kwargs):
    if created:
        suffix = get_random_string(length=32)
        paper_title = instance.paper_title
        title = instance.title

        slug = paper_title or title
        slug = slugify(slug)
        if not slug:
            slug += suffix
        instance.slug = slug
        instance.save()


@receiver(post_save, sender=Paper, dispatch_uid="add_unified_doc")
def add_unified_doc(created, instance, **kwargs):
    if created:
        unified_doc = ResearchhubUnifiedDocument.objects.filter(
            paper__id=instance.id
        ).first()
        if unified_doc is None:
            try:
                unified_doc = ResearchhubUnifiedDocument.objects.create(
                    document_type=PAPER_DOC_TYPE,
                    score=instance.score,
                )
                unified_doc.hubs.add(*instance.hubs.all())
                instance.unified_document = unified_doc
                instance.save()
            except Exception as e:
                log_error("EXCPETION (add_unified_doc): ", e)


@receiver(
    post_save, sender="purchase.Payment", dispatch_uid="update_paper_journal_status"
)
def update_paper_journal_status(sender, instance, created, **kwargs):
    """
    When a payment is received for a paper, update its version to be part
    of the ResearchHub journal and create a new DOI.

    This signal handler checks if the payment is for a Paper model and if so,
    finds the PaperVersion for that paper, sets its journal field to RESEARCHHUB,
    and creates a new DOI for both the PaperVersion and Paper.
    """
    if not created:
        return

    try:
        paper_content_type = ContentType.objects.get_for_model(Paper)

        if instance.content_type_id == paper_content_type.id:
            paper_id = instance.object_id
            paper = Paper.objects.get(id=paper_id)

            try:
                paper_version = PaperVersion.objects.get(paper=paper)
                paper_versions = PaperVersion.objects.filter(
                    original_paper=paper_version.original_paper
                )
                paper_versions.update(journal=PaperVersion.RESEARCHHUB)
                paper.unified_document.hubs.add(settings.RESEARCHHUB_JOURNAL_ID)
                paper.unified_document.save()

                # Refresh the paper_version object to get the updated journal value
                paper_version.refresh_from_db()

                # Create a new DOI for the ResearchHub journal publication
                doi = DOI(journal=PaperVersion.RESEARCHHUB)

                # Get authors for DOI registration
                authors = paper.authors.all()

                # Register DOI with Crossref
                crossref_response = doi.register_doi_for_paper(
                    authors=list(authors),
                    title=paper.title or paper.paper_title,
                    rh_paper=paper,
                )

                if crossref_response.status_code == 200:
                    # Update paper with new DOI
                    paper.doi = doi.doi
                    paper.save()

                    # Update paper version with new base DOI
                    paper_version.base_doi = doi.base_doi
                    paper_version.save()

                    log_info(f"Successfully created DOI {doi.doi} for paper {paper_id}")
                else:
                    log_error(
                        Exception(f"Failed to register DOI for paper {paper_id}"),
                        f"Failed to register DOI for paper {paper_id}: "
                        f"Crossref returned status {crossref_response.status_code}",
                    )

                # Add paper to ResearchHub journal hub
                paper.unified_document.hubs.add(settings.RESEARCHHUB_JOURNAL_ID)
                paper.unified_document.save()

            except PaperVersion.DoesNotExist:
                log_error(
                    Exception(f"No PaperVersion found for paper {paper_id}"),
                    f"No PaperVersion found for paper {paper_id}, "
                    f"skipping journal update",
                )

    except Exception as e:
        log_error(e, message="Error updating paper journal status")


@receiver(post_save, sender=Paper, dispatch_uid="update_paper_knn_vector_on_save")
def update_paper_knn_vector_on_save(sender, instance, created, update_fields, **kwargs):
    """
    Update paper_knn index vector when paper is saved.

    This signal handler listens for paper saves and triggers vector generation:
    - For new papers: Generate vector after paper is created
    - For updates: Only regenerate if abstract field was changed

    It queues a Celery task to generate the vector embedding.
    """
    # Check if we should process this save
    should_process = False

    if created:
        # New paper - generate vector if it has an abstract
        should_process = True
    else:
        # Updated paper - only process if abstract was in update_fields
        if update_fields and "abstract" in update_fields:
            should_process = True
        elif update_fields is None:
            should_process = True

    if not should_process:
        return

    if not instance.abstract or instance.abstract.strip() == "":
        logger.debug(f"Paper {instance.id} has no abstract, skipping vector generation")
        return

    try:
        from paper.tasks.tasks import generate_abstract_vector_for_paper

        # For new papers, skip if vector already exists
        # For updates, force regeneration (skip_existing=False)
        skip_existing = created

        # Queue vector generation task with a delay to ensure indexing is complete
        generate_abstract_vector_for_paper.apply_async(
            args=(instance.id, skip_existing),
            countdown=5,  # 5 second delay to ensure OpenSearch indexing is complete
        )

        action = "creation" if created else "abstract update"
        logger.info(f"Queued vector generation for paper {instance.id} after {action}")
    except ImportError:
        logger.warning(
            "paper.tasks.tasks.generate_abstract_vector_for_paper not available, "
            "skipping vector generation"
        )
    except Exception as e:
        log_error(
            e,
            message=f"Failed to queue vector generation for paper {instance.id}",
        )


@receiver(post_delete, sender=Paper, dispatch_uid="remove_paper_from_knn_index")
def remove_paper_from_knn_index(sender, instance, **kwargs):
    """
    Remove paper from paper_knn index when paper is deleted.

    This signal handler listens for paper deletions and removes the
    corresponding document from the paper_knn OpenSearch index.
    """
    try:
        from search.documents.paper import PaperDocument

        document = PaperDocument()
        client = document._index._get_connection()
        knn_index_name = "paper_knn"

        # Check if paper_knn index exists
        try:
            client.indices.get(index=knn_index_name)
        except Exception:
            # paper_knn index doesn't exist, nothing to clean up
            logger.debug(
                f"paper_knn index does not exist, skipping deletion for paper {instance.id}"
            )
            return

        # Delete document from paper_knn index
        try:
            client.delete(index=knn_index_name, id=str(instance.id))
            logger.info(
                f"Successfully removed paper {instance.id} from {knn_index_name} index"
            )
        except Exception as delete_error:
            # Document might not exist in paper_knn, which is fine
            logger.debug(
                f"Paper {instance.id} not found in {knn_index_name} "
                f"(may not have been indexed): {str(delete_error)}"
            )

    except Exception as e:
        # Log error but don't fail the deletion
        log_error(
            e,
            message=f"Failed to remove paper {instance.id} from paper_knn index",
        )
