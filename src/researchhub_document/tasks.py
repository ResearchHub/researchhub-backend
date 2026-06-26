import logging
from datetime import timedelta

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from mailing_list.lib import base_email_context, send_email
from researchhub.celery import (
    QUEUE_HOT_SCORE,
    QUEUE_NOTIFICATION,
    QUEUE_PAPER_MISC,
    app,
)
from researchhub_document.models import ResearchhubPost, ResearchJourney
from researchhub_document.related_models.constants.document_type import (
    PREREGISTRATION,
)
from utils import sentry
from utils.doi import DOI

logger = logging.getLogger(__name__)

PROPOSAL_ENTERED_JOURNAL_EMAIL_SUBJECT = (
    "Your proposal is now in the ResearchHub Journal"
)


def build_proposal_entered_journal_email_context(
    proposal: ResearchhubPost,
) -> dict[str, object]:
    """Build the email context for a proposal entering the journal."""
    proposal_url = proposal.unified_document.frontend_view_link()
    author = proposal.created_by
    author_name = author.first_name or author.full_name() or "there"
    proposal_title = proposal.title or "your proposal"
    message = (
        f"Hello {author_name},\n\n"
        f'Your funded proposal "{proposal_title}" is now in the ResearchHub Journal.'
        "\n\nThe next step is to create a Registered Report from your proposal."
    )

    return {
        **base_email_context,
        "action": {
            "cta_label": "Create Registered Report",
            "frontend_view_link": proposal_url,
            "message": message,
        },
        "subject": PROPOSAL_ENTERED_JOURNAL_EMAIL_SUBJECT,
    }


@app.task(queue=QUEUE_NOTIFICATION)
def send_proposal_entered_journal_email(
    journey_id: int,
) -> dict[str, list[str]] | None:
    """Send the author an email when their proposal enters the journal."""
    journey = (
        ResearchJourney.objects.filter(id=journey_id)
        .select_related(
            "preregistration_post__created_by",
            "preregistration_post__unified_document",
        )
        .first()
    )
    if journey is None:
        logger.warning(
            "Skipping journal entry email because the journey does not exist.",
            extra={"journey_id": journey_id},
        )
        return None
    if not journey.is_in_journal:
        return None

    proposal = journey.preregistration_post
    if proposal is None or proposal.created_by_id is None:
        return None
    if not proposal.created_by.email:
        return None

    return send_email(
        [proposal.created_by.email],
        "general_email_message.txt",
        PROPOSAL_ENTERED_JOURNAL_EMAIL_SUBJECT,
        build_proposal_entered_journal_email_context(proposal),
        html_template="general_email_message.html",
    )


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
