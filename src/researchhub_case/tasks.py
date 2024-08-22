from django.db import transaction

from notification.models import Notification
from paper.related_models.paper_model import Paper
from reputation.related_models.paper_reward import PaperReward
from researchhub.celery import QUEUE_AUTHOR_CLAIM, app
from researchhub_case.constants.case_constants import APPROVED, DENIED, INITIATED
from researchhub_case.models import AuthorClaimCase
from researchhub_case.utils.author_claim_case_utils import (
    get_new_validation_token,
    reward_author_claim_case,
    send_approval_email,
    send_rejection_email,
    send_validation_email,
    send_verification_email,
)
from researchhub_document.related_models.constants.document_type import (
    FILTER_AUTHOR_CLAIMED,
)
from utils import sentry
from utils.parsers import get_pure_doi


@app.task(queue=QUEUE_AUTHOR_CLAIM)
def trigger_email_validation_flow(
    case_id,
):
    instance = AuthorClaimCase.objects.get(id=case_id)

    if instance.status == INITIATED:
        try:
            [generated_time, token] = get_new_validation_token()
            instance.token_generated_time = generated_time
            instance.validation_token = token
            # Note: intentionally sending email before incrementing attempt
            send_validation_email(instance)

            instance.validation_attempt_count += 1
            instance.save()
        except Exception as exception:
            sentry.log_error(exception)


@app.task(queue=QUEUE_AUTHOR_CLAIM)
def after_approval_flow(case_id):
    instance = AuthorClaimCase.objects.get(id=case_id)

    if instance.status != APPROVED:
        Exception(
            "Cannot continue with after approval flow since claim is not APPROVED"
        )

    requestor = instance.requestor
    try:
        with transaction.atomic():
            paper_reward = instance.paper_reward
            paper_reward.distribute_paper_rewards()
            notification = Notification.objects.create(
                item=instance,
                notification_type=Notification.PAPER_CLAIM_PAYOUT,
                recipient=requestor,
                action_user=requestor,
            )
            notification.send_notification()
    except Exception as exception:
        sentry.log_error(exception)


@app.task(queue=QUEUE_AUTHOR_CLAIM)
def after_rejection_flow(
    case_id,
    notify_user=False,
):
    # FIXME: Send rejection email (and in-app notification)
    pass
