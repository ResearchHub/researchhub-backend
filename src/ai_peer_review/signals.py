from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from ai_peer_review.models import ProposalReview, Status
from ai_peer_review.tasks import (
    auto_run_proposal_key_insights_for_ud,
    auto_run_proposal_review_for_grant_application,
    auto_run_proposal_reviews_for_post,
)
from purchase.models import GrantApplication
from researchhub_comment.models import RhCommentModel
from researchhub_document.models import ResearchhubPost
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from review.models import Review


@receiver(
    post_save,
    sender=ResearchhubPost,
    dispatch_uid="ai_peer_review_auto_run_on_post_save",
)
def trigger_proposal_reviews_on_post_save(sender, instance, **kwargs):
    if instance.document_type != PREREGISTRATION:
        return

    post_id = instance.id

    def _enqueue():
        auto_run_proposal_reviews_for_post.delay(post_id, force=False)

    transaction.on_commit(_enqueue)


@receiver(
    post_save,
    sender=GrantApplication,
    dispatch_uid="ai_peer_review_auto_run_on_grant_application",
)
def trigger_proposal_reviews_on_grant_application(sender, instance, created, **kwargs):
    if not created:
        return

    application_id = instance.id

    def _enqueue():
        auto_run_proposal_review_for_grant_application.delay(
            application_id, force=False
        )

    transaction.on_commit(_enqueue)


@receiver(post_save, sender=Review, dispatch_uid="ai_peer_review_ki_on_review_assessed")
def trigger_key_insights_on_review_assessed(sender, instance, **kwargs):
    if not instance.is_assessed or instance.unified_document_id is None:
        return

    ud_id = instance.unified_document_id

    def _enqueue():
        auto_run_proposal_key_insights_for_ud.delay(ud_id, force=False)

    transaction.on_commit(_enqueue)


@receiver(
    post_save,
    sender=RhCommentModel,
    dispatch_uid="ai_peer_review_ki_on_assessed_comment_updated",
)
def trigger_key_insights_on_assessed_comment_updated(
    sender, instance, created, **kwargs
):
    """Rerun insights generation when a comment that is considered "assessed" is saved."""
    if created or instance.is_removed:
        return

    assessed_qs = instance.reviews.filter(
        is_assessed=True, unified_document_id__isnull=False
    )
    if not assessed_qs.exists():
        return

    ud_id = assessed_qs.values_list("unified_document_id", flat=True).first()

    def _enqueue():
        auto_run_proposal_key_insights_for_ud.delay(ud_id, force=False)

    transaction.on_commit(_enqueue)


@receiver(
    post_save,
    sender=ProposalReview,
    dispatch_uid="ai_peer_review_ki_on_proposal_review_completed",
)
def trigger_key_insights_on_proposal_review_completed(sender, instance, **kwargs):
    if instance.status != Status.COMPLETED:
        return

    ud_id = instance.unified_document_id

    def _enqueue():
        auto_run_proposal_key_insights_for_ud.delay(ud_id, force=False)

    transaction.on_commit(_enqueue)
