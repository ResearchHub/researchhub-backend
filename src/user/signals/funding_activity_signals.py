import logging

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from paper.models import Paper
from purchase.models import Fundraise, Purchase
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
from utils.sentry import log_error

logger = logging.getLogger(__name__)

_content_type_cache = {}


def _get_content_type(model):
    """Return ContentType for model, cached."""
    if model not in _content_type_cache:
        _content_type_cache[model] = ContentType.objects.get_for_model(model)
    return _content_type_cache[model]


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
    """Schedule FundingActivity when Purchase is PAID (BOOST only). Fundraise payouts are created when escrow is PAID (on_escrow_paid)."""
    if instance.paid_status != Purchase.PAID:
        return
    if instance.purchase_type != Purchase.BOOST:
        return

    ct_paper = _get_content_type(Paper)
    ct_post = _get_content_type(ResearchhubPost)
    if instance.content_type_id not in (ct_paper.id, ct_post.id):
        return

    def schedule():
        try:
            create_funding_activity_task.delay(
                FundingActivity.TIP_DOCUMENT,
                instance.pk,
            )
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
    """Schedule FundingActivity when Escrow is PAID (BOUNTY or FUNDRAISE)."""
    if instance.status != Escrow.PAID:
        return

    if instance.hold_type == Escrow.BOUNTY:

        def schedule_bounty():
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

        transaction.on_commit(schedule_bounty)
        return

    if instance.hold_type == Escrow.FUNDRAISE:
        fundraise = Fundraise.objects.filter(escrow=instance).first()
        if fundraise is not None:

            def schedule_fundraise_funding():
                try:
                    for purchase in fundraise.purchases.filter(
                        paid_status=Purchase.PAID
                    ):
                        create_funding_activity_task.delay(
                            FundingActivity.FUNDRAISE_PAYOUT,
                            purchase.pk,
                        )
                    for contribution in fundraise.usd_contributions.filter(
                        is_refunded=False
                    ):
                        create_funding_activity_task.delay(
                            FundingActivity.FUNDRAISE_PAYOUT_USD,
                            contribution.pk,
                        )
                except Exception as e:
                    log_error(
                        e,
                        message="Failed to schedule funding activity tasks for "
                        "fundraise %s" % fundraise.pk,
                    )

            transaction.on_commit(schedule_fundraise_funding)


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

    if instance.distribution_type == "PURCHASE":
        ct_purchase = _get_content_type(Purchase)
        ct_comment = _get_content_type(RhCommentModel)
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
        except Exception as e:
            log_error(
                e,
                message="Failed to schedule funding activity task for Distribution %s"
                % instance.pk,
            )

    transaction.on_commit(schedule)
