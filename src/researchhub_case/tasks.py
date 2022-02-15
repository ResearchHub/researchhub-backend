from researchhub.celery import app
from researchhub_case.models import AuthorClaimCase
from researchhub_case.utils.author_claim_case_utils import (
  get_new_validation_token,
  reward_author_claim_case,
  send_validation_email,
  send_approval_email,
  send_rejection_email,
)
from user.utils import merge_author_profiles
from utils import sentry
from researchhub_case.constants.case_constants import (
    APPROVED, INITIATED, DENIED
)


@app.task
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
            print('exception', exception)
            sentry.log_error(exception)



@app.task
def trigger_approval_flow(
    case_id
):
    instance = AuthorClaimCase.objects.get(id=case_id)
    if (
        instance.status == APPROVED
        and instance.validation_token is not None
    ):
        try:
            # logical ordering
            requestor_author = instance.requestor.author_profile
            target_author_papers = instance.target_author.authored_papers.all()
            reward_author_claim_case(requestor_author, target_author_papers)
            merge_author_profiles(requestor_author, instance.target_author)
            # instance.target_author = requestor_author
            instance.save()
            send_approval_email(instance)
        except Exception as exception:
            print("merge_author_upon_approval: ", exception)
            sentry.log_error(exception)

@app.task
def trigger_rejection_flow(
    case_id,
    notify_user=False,
):
    instance = AuthorClaimCase.objects.get(id=case_id)
    if instance.status == DENIED and notify_user == True:
        send_rejection_email(instance)
