import logging

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from purchase.models import Purchase
from reputation.models import Distribution
from reputation.related_models.escrow import Escrow, EscrowRecipients
from user.related_models.funding_activity_model import FundingActivity
from user.tasks.funding_activity_tasks import create_funding_activity_task
from utils.sentry import log_error

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
    if instance.paid_status != Purchase.PAID:
        return
    if instance.purchase_type not in (
        Purchase.BOOST,
        Purchase.FUNDRAISE_CONTRIBUTION,
    ):
        return

    source_type = (
        FundingActivity.TIP_DOCUMENT
        if instance.purchase_type == Purchase.BOOST
        else FundingActivity.FUNDRAISE_PAYOUT
    )

    def schedule():
        try:
            create_funding_activity_task.delay(source_type, instance.pk)
        except Exception as e:
            log_error(
                e,
                message="Failed to schedule funding activity task for Purchase %s"
                % instance.pk,
            )

    transaction.on_commit(schedule)


@receiver(
    post_save,
    sender=Escrow,
    dispatch_uid="funding_activity_on_escrow_paid",
)
def on_escrow_paid(sender, instance, created, **kwargs):
    """Schedule FundingActivity for each EscrowRecipients when Escrow is PAID (BOUNTY)."""
    if instance.status != Escrow.PAID or instance.hold_type != Escrow.BOUNTY:
        return

    def schedule():
        try:
            for rec in EscrowRecipients.objects.filter(escrow=instance):
                create_funding_activity_task.delay(
                    FundingActivity.BOUNTY_PAYOUT,
                    rec.pk,
                )
        except Exception as e:
            log_error(
                e,
                message="Failed to schedule funding activity tasks for Escrow %s"
                % instance.pk,
            )

    transaction.on_commit(schedule)


@receiver(
    post_save,
    sender=Distribution,
    dispatch_uid="funding_activity_on_distribution_created",
)
def on_distribution_created(sender, instance, created, **kwargs):
    """Schedule FundingActivity when Distribution is created (PURCHASE tip or fee types)."""
    if not created:
        return
    if instance.distribution_type not in DISTRIBUTION_TYPES_FOR_FUNDING:
        return

    source_type = (
        FundingActivity.TIP_REVIEW
        if instance.distribution_type == "PURCHASE"
        else FundingActivity.FEE
    )

    def schedule():
        try:
            create_funding_activity_task.delay(source_type, instance.pk)
        except Exception as e:
            log_error(
                e,
                message="Failed to schedule funding activity task for Distribution %s"
                % instance.pk,
            )

    transaction.on_commit(schedule)
