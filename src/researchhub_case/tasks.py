from researchhub.celery import QUEUE_AUTHOR_CLAIM, app
from researchhub_case.constants.case_constants import INITIATED
from researchhub_case.models import AuthorClaimCase
from researchhub_case.utils.author_claim_case_utils import (
    get_new_validation_token,
    send_validation_email,
)
from utils import sentry


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
    # The paper-claim RSC payout has been retired. Approving a claim no longer
    # distributes RSC or sends a payout notification.

    return


@app.task(queue=QUEUE_AUTHOR_CLAIM)
def after_rejection_flow(
    case_id,
    notify_user=False,
):
    return
