from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import Signal, receiver

from ai_peer_review.tasks import (
    auto_run_proposal_review_for_grant_application,
    auto_run_proposal_reviews_for_post,
)
from purchase.models import GrantApplication

preregistration_substantively_updated = Signal()


@receiver(
    preregistration_substantively_updated,
    dispatch_uid="ai_peer_review_on_prereg_substantively_updated",
)
def enqueue_proposal_review_after_prereg_substantive_update(
    sender, post_id: int, **kwargs
):
    """Enqueue guarded AI proposal review for all grants linked to this post."""

    def _enqueue(pid=post_id):
        auto_run_proposal_reviews_for_post.delay(pid, force=False)

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
