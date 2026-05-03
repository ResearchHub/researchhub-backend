import logging

from ai_peer_review.models import ProposalReview, Status
from ai_peer_review.services.auto_run_guards import AutoRunGuardsService
from ai_peer_review.services.proposal_key_insights_service import (
    ProposalKeyInsightsService,
)
from ai_peer_review.services.proposal_review_service import (
    reset_proposal_review_for_rerun,
    run_proposal_review,
)
from ai_peer_review.services.rfp_summary_service import run_rfp_summary
from purchase.models import GrantApplication
from researchhub.celery import app
from researchhub_document.models import ResearchhubPost
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from utils import sentry

logger = logging.getLogger(__name__)


@app.task
def process_proposal_review_task(review_id: int):

    run_proposal_review(review_id)


@app.task
def process_rfp_summary_task(rfp_summary_id: int):

    run_rfp_summary(rfp_summary_id)


@app.task
def auto_run_proposal_reviews_for_post(post_id: int, force: bool = False) -> None:
    """
    For a proposal (preregistration) post, enqueue a guarded AI proposal review per linked grant.
    """
    try:
        post = ResearchhubPost.objects.select_related("unified_document").get(
            pk=post_id
        )
    except ResearchhubPost.DoesNotExist:
        logger.warning("auto_run_proposal_reviews_for_post: post %s not found", post_id)
        return

    if post.document_type != PREREGISTRATION:
        return

    applications = GrantApplication.objects.filter(
        preregistration_post_id=post_id
    ).select_related("grant")
    for application in applications:
        review, _created = ProposalReview.objects.get_or_create(
            unified_document=post.unified_document,
            grant=application.grant,
            defaults={
                "status": Status.PENDING,
            },
        )

        guarded_run_proposal_review.delay(review.id, force)


@app.task
def auto_run_proposal_review_for_grant_application(
    grant_application_id: int, force: bool = False
) -> None:
    """
    Enqueue a single guarded AI proposal review for one (post, grant) pair.
    """
    try:
        application = GrantApplication.objects.select_related(
            "grant",
            "preregistration_post",
            "preregistration_post__unified_document",
        ).get(pk=grant_application_id)
    except GrantApplication.DoesNotExist:
        logger.warning(
            "auto_run_proposal_review_for_grant_application: "
            "GrantApplication %s not found",
            grant_application_id,
        )
        return

    post = application.preregistration_post
    if post.document_type != PREREGISTRATION:
        return

    review, _created = ProposalReview.objects.get_or_create(
        unified_document=post.unified_document,
        grant=application.grant,
        defaults={
            "status": Status.PENDING,
        },
    )

    guarded_run_proposal_review.delay(review.id, force)


@app.task
def auto_run_proposal_key_insights_for_ud(
    unified_document_id: int, force: bool = False
) -> None:
    """Enqueue guarded key-insights runs for every completed proposal review on this document."""
    reviews = ProposalReview.objects.filter(
        unified_document_id=unified_document_id,
        status=Status.COMPLETED,
    ).values_list("id", flat=True)
    for rid in reviews:
        guarded_run_proposal_key_insights.delay(rid, force)


@app.task
def guarded_run_proposal_review(review_id: int, force: bool = False) -> None:
    try:
        review = ProposalReview.objects.select_related("unified_document", "grant").get(
            pk=review_id
        )
    except ProposalReview.DoesNotExist:
        logger.warning("guarded_run_proposal_review: review %s not found", review_id)
        return

    skip, reason = AutoRunGuardsService.should_skip_proposal_review(review, force=force)
    if skip:
        logger.warning(
            "guarded_run_proposal_review: skip review=%s reason=%s",
            review_id,
            reason,
        )
        sentry.log_info(
            f"guarded_run_proposal_review skipped by guard review_id={review_id} "
            f"reason={reason} force={force}"
        )
        return

    reset_proposal_review_for_rerun(review)

    try:
        run_proposal_review(review_id)
    except Exception:
        logger.exception("guarded_run_proposal_review failed review=%s", review_id)


@app.task
def guarded_run_proposal_key_insights(review_id: int, force: bool = False) -> None:
    try:
        review = ProposalReview.objects.select_related("unified_document", "grant").get(
            pk=review_id
        )
    except ProposalReview.DoesNotExist:
        logger.warning(
            "guarded_run_proposal_key_insights: review %s not found", review_id
        )
        return

    skip, reason = AutoRunGuardsService.should_skip_key_insights(review, force=force)
    if skip:
        logger.warning(
            "guarded_run_proposal_key_insights: skip review=%s reason=%s",
            review_id,
            reason,
        )
        sentry.log_info(
            f"guarded_run_proposal_key_insights skipped by guard review_id={review_id} "
            f"reason={reason} force={force}"
        )
        return

    try:
        ProposalKeyInsightsService().run(review_id, force=force)
    except Exception:
        logger.exception(
            "guarded_run_proposal_key_insights failed review=%s", review_id
        )
