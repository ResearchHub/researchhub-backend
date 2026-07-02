import logging
from datetime import timedelta

from django.utils import timezone

from researchhub.celery import QUEUE_PAPER_MISC, app
from researchhub_document.models import ResearchhubPost
from researchhub_document.related_models.constants.document_type import (
    PREREGISTRATION,
)
from utils.doi import DOI

logger = logging.getLogger(__name__)


@app.task(queue=QUEUE_PAPER_MISC)
def assign_preregistration_dois():
    week_ago = timezone.now() - timedelta(days=7)

    eligible_posts = ResearchhubPost.objects.filter(
        document_type=PREREGISTRATION,
        doi__isnull=True,
        created_date__lte=week_ago,
        unified_document__is_removed=False,
        flags__isnull=True,
    ).select_related("created_by__author_profile", "unified_document")

    total = eligible_posts.count()
    assigned_count = 0

    for post in eligible_posts:
        try:
            doi = DOI()
            author = post.created_by.author_profile
            response = doi.register_doi_for_post([author], post.title, post)

            if response.status_code == 200:
                post.doi = doi.doi
                post.save(update_fields=["doi"])
                assigned_count += 1
            else:
                logger.error(
                    f"Crossref API failure for post {post.id}: "
                    f"status {response.status_code}"
                )
        except Exception:
            logger.exception(f"Failed to assign DOI to post {post.id}")

    logger.info(f"Assigned DOIs to {assigned_count}/{total} eligible preregistrations")
