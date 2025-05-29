from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.crypto import get_random_string
from django.utils.text import slugify

from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import (
    PAPER as PAPER_DOC_TYPE,
)
from utils.doi import DOI
from utils.sentry import log_error

from .models import Paper
from .related_models.paper_version import PaperVersion


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

                    log_error(
                        f"Successfully created DOI {doi.doi} for paper {paper_id}"
                    )
                else:
                    log_error(
                        f"Failed to register DOI for paper {paper_id}: "
                        f"Crossref returned status {crossref_response.status_code}"
                    )

                # Add paper to ResearchHub journal hub
                paper.unified_document.hubs.add(settings.RESEARCHHUB_JOURNAL_ID)
                paper.unified_document.save()

            except PaperVersion.DoesNotExist:
                log_error(
                    f"No PaperVersion found for paper {paper_id}, "
                    f"skipping journal update"
                )

    except Exception as e:
        log_error(f"Error updating paper journal status: {e}")
