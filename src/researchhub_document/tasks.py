import logging
from datetime import timedelta

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from researchhub.celery import QUEUE_HOT_SCORE, QUEUE_PAPER_MISC, app
from researchhub_document.models import ResearchhubPost
from researchhub_document.related_models.constants.document_type import (
    DISCUSSION,
    PREREGISTRATION,
)
from utils import sentry
from utils.doi import DOI

logger = logging.getLogger(__name__)


@app.task(queue=QUEUE_PAPER_MISC)
def assign_post_dois():
    week_ago = timezone.now() - timedelta(days=7)

    eligible_posts = (
        ResearchhubPost.objects.filter(
            document_type__in=[DISCUSSION, PREREGISTRATION],
            doi__isnull=True,
            created_date__lte=week_ago,
            unified_document__is_removed=False,
            flags__isnull=True,
        )
        .select_related("created_by__author_profile", "unified_document")
    )

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

    logger.info(f"Assigned DOIs to {assigned_count}/{total} eligible posts")


@app.task(queue=QUEUE_HOT_SCORE)
def recalc_hot_score_task(instance_content_type_id, instance_id):
    content_type = ContentType.objects.get(id=instance_content_type_id)
    model_name = content_type.model
    model_class = content_type.model_class()
    uni_doc = None

    try:
        if model_name in [
            "bounty",
            "contribution",
            "paper",
            "researchhubpost",
        ]:
            uni_doc = model_class.objects.get(id=instance_id).unified_document
        elif model_name == "citation":
            uni_doc = model_class.objects.get(id=instance_id).source

        if uni_doc:
            # Recalculate and save hot score on the unified document
            hot_score, _ = uni_doc.calculate_hot_score(should_save=True)

    except Exception as error:
        sentry.log_error(error)
