import logging

from purchase.models import Purchase, UsdFundraiseContribution
from reputation.models import Distribution
from reputation.related_models.escrow import EscrowRecipients
from researchhub.celery import QUEUE_REPUTATION, app
from user.related_models.funding_activity_model import FundingActivity
from user.services.funding_activity_service import FundingActivityService

logger = logging.getLogger(__name__)

# Map source_type to model class for fetching the source object by pk
_SOURCE_TYPE_MODEL = {
    FundingActivity.FUNDRAISE_PAYOUT: Purchase,
    FundingActivity.FUNDRAISE_PAYOUT_USD: UsdFundraiseContribution,
    FundingActivity.BOUNTY_PAYOUT: EscrowRecipients,
    FundingActivity.TIP_DOCUMENT: Purchase,
    FundingActivity.TIP_REVIEW: Distribution,
    FundingActivity.FEE: Distribution,
}


@app.task(queue=QUEUE_REPUTATION, max_retries=3, retry_backoff=True)
def create_funding_activity_task(source_type, source_id):
    """
    Create a FundingActivity record for the given source.
    Idempotent: if one already exists for this source, the service returns it.

    Args:
        source_type: One of FundingActivity.FUNDRAISE_PAYOUT, FUNDRAISE_PAYOUT_USD,
            BOUNTY_PAYOUT, TIP_DOCUMENT, TIP_REVIEW, FEE.
        source_id: Primary key of the source object (Purchase, UsdFundraiseContribution,
            EscrowRecipients, or Distribution).
    """
    if source_type not in _SOURCE_TYPE_MODEL:
        logger.warning(
            "create_funding_activity_task: unknown source_type=%s", source_type
        )
        return

    model_class = _SOURCE_TYPE_MODEL[source_type]
    try:
        source_object = model_class.objects.get(pk=source_id)
    except model_class.DoesNotExist:
        logger.warning(
            "create_funding_activity_task: %s pk=%s not found",
            model_class.__name__,
            source_id,
        )
        return

    try:
        activity = FundingActivityService.create_funding_activity(
            source_type=source_type,
            source_object=source_object,
        )
        if activity is not None:
            logger.debug(
                "create_funding_activity_task: created FundingActivity pk=%s",
                activity.pk,
            )
    except Exception as e:
        logger.exception(
            "create_funding_activity_task: failed for source_type=%s "
            "source_id=%s: %s",
            source_type,
            source_id,
            e,
        )
        raise
