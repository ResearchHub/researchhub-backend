import logging

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from paper.models import Paper
from purchase.models import Purchase
from reputation.models import Distribution
from reputation.related_models.escrow import Escrow, EscrowRecipients
from researchhub_comment.constants.rh_comment_thread_types import (
    COMMUNITY_REVIEW,
    PEER_REVIEW,
)
from researchhub_comment.models import RhCommentModel
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from user.related_models.funding_activity_model import FundingActivity
from user.tasks.funding_activity_tasks import create_funding_activity_task

logger = logging.getLogger(__name__)

DISTRIBUTION_TYPES_FOR_FUNDING = (
    "PURCHASE",
    "BOUNTY_DAO_FEE",
    "BOUNTY_RH_FEE",
    "SUPPORT_RH_FEE",
)


@receiver(
    post_save,
    sender=Purchase,
    dispatch_uid="funding_activity_on_purchase_paid",
)
def on_purchase_paid(sender, instance, created, **kwargs):
    """Schedule FundingActivity when Purchase is PAID (BOOST or FUNDRAISE_CONTRIBUTION)."""
    try:
        if instance.paid_status != Purchase.PAID:
            return
        if instance.purchase_type not in (
            Purchase.BOOST,
            Purchase.FUNDRAISE_CONTRIBUTION,
        ):
            return

        if instance.purchase_type == Purchase.BOOST:
            ct_paper = ContentType.objects.get_for_model(Paper)
            ct_post = ContentType.objects.get_for_model(ResearchhubPost)
            if instance.content_type_id not in (ct_paper.id, ct_post.id):
                return

        source_type = (
            FundingActivity.TIP_DOCUMENT
            if instance.purchase_type == Purchase.BOOST
            else FundingActivity.FUNDRAISE_PAYOUT
        )

        def schedule():
            try:
                create_funding_activity_task.delay(source_type, instance.pk)
            except Exception:
                logger.exception(
                    "Failed to schedule funding activity task for Purchase %s",
                    instance.pk,
                )

        transaction.on_commit(schedule)
    except Exception:
        logger.exception(
            "Funding activity signal failed for Purchase %s",
            instance.pk,
        )


@receiver(
    post_save,
    sender=Escrow,
    dispatch_uid="funding_activity_on_escrow_paid",
)
def on_escrow_paid(sender, instance, created, **kwargs):
    """Schedule FundingActivity for each EscrowRecipients when Escrow is PAID (BOUNTY)."""
    try:
        if instance.status != Escrow.PAID or instance.hold_type != Escrow.BOUNTY:
            return

        def schedule():
            try:
                for rec in EscrowRecipients.objects.filter(escrow=instance):
                    create_funding_activity_task.delay(
                        FundingActivity.BOUNTY_PAYOUT,
                        rec.pk,
                    )
            except Exception:
                logger.exception(
                    "Failed to schedule funding activity tasks for Escrow %s",
                    instance.pk,
                )

        transaction.on_commit(schedule)
    except Exception:
        logger.exception(
            "Funding activity signal failed for Escrow %s",
            instance.pk,
        )


@receiver(
    post_save,
    sender=Distribution,
    dispatch_uid="funding_activity_on_distribution_created",
)
def on_distribution_created(sender, instance, created, **kwargs):
    """Schedule FundingActivity when Distribution is created (PURCHASE tip or fee types)."""
    try:
        if not created:
            return
        if instance.distribution_type not in DISTRIBUTION_TYPES_FOR_FUNDING:
            return

        if instance.distribution_type == "PURCHASE":
            ct_purchase = ContentType.objects.get_for_model(Purchase)
            ct_comment = ContentType.objects.get_for_model(RhCommentModel)
            if instance.proof_item_content_type_id != ct_purchase.id:
                return
            try:
                proof_purchase = Purchase.objects.get(pk=instance.proof_item_object_id)
            except Purchase.DoesNotExist:
                return
            if proof_purchase.content_type_id != ct_comment.id:
                return
            comment = proof_purchase.item
            if comment is None or getattr(comment, "comment_type", None) not in (
                PEER_REVIEW,
                COMMUNITY_REVIEW,
            ):
                return

        source_type = (
            FundingActivity.TIP_REVIEW
            if instance.distribution_type == "PURCHASE"
            else FundingActivity.FEE
        )

        def schedule():
            try:
                create_funding_activity_task.delay(source_type, instance.pk)
            except Exception:
                logger.exception(
                    "Failed to schedule funding activity task for Distribution %s",
                    instance.pk,
                )

        transaction.on_commit(schedule)
    except Exception:
        logger.exception(
            "Funding activity signal failed for Distribution %s",
            instance.pk,
        )
