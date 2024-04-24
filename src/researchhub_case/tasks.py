from notification.models import Notification
from paper.related_models.paper_model import Paper
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
from user.utils import move_paper_to_author
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

            print("instance", instance)

            instance.validation_attempt_count += 1
            instance.save()
        except Exception as exception:
            sentry.log_error(exception)


@app.task(queue=QUEUE_AUTHOR_CLAIM)
def after_approval_flow(case_id):
    instance = AuthorClaimCase.objects.get(id=case_id)

    if instance.status != APPROVED:
        return
    if instance.target_paper is None and instance.target_paper_doi is None:
        raise Exception("Cannot approve claim because paper was not found")

    requestor = instance.requestor
    try:
        total_amount_paid = 0

        if requestor.is_verified is False:
            # Set author profile to verified
            requestor.set_verified(is_verified=True)

            # In-app notification about verification approval
            verification_notification = Notification.objects.create(
                item=instance,
                notification_type=Notification.ACCOUNT_VERIFIED,
                recipient=requestor,
                action_user=requestor,
            )
            verification_notification.send_notification()
            send_verification_email(instance, context={})

        if instance.target_paper:
            reward_author_claim_case(requestor.author_profile, instance.target_paper)

            # Clear caches associated with paper
            instance.target_paper.unified_document.update_filter(FILTER_AUTHOR_CLAIMED)

            # In-app notification about paper approval
            claim_notification = Notification.objects.create(
                item=instance,
                notification_type=Notification.PAPER_CLAIMED,
                unified_document=instance.target_paper.unified_document,
                recipient=requestor,
                action_user=requestor,
            )
            claim_notification.send_notification()
        else:
            # Paper not associated with case. Likely because user claimed via DOI and not via paper ID.
            # We have a process to try and upload a paper that is claimed via DOI in case it does not exist.
            # Let's fetch it and

            try:
                doi = get_pure_doi(instance.target_paper_doi)
                paper = Paper.objects.get(doi=doi)
                instance.target_paper = paper
                instance.save()
            except Exception as e:
                # Paper does not exist
                pass

        if instance.target_paper:
            move_paper_to_author(
                instance.target_paper, instance.requestor.author_profile
            )

        send_approval_email(instance, context={"total_amount_paid": total_amount_paid})
    except Exception as exception:
        print("exception", exception)
        sentry.log_error(exception)


@app.task(queue=QUEUE_AUTHOR_CLAIM)
def after_rejection_flow(
    case_id,
    notify_user=False,
):
    instance = AuthorClaimCase.objects.get(id=case_id)
    if instance.status == DENIED and notify_user is True:
        send_rejection_email(instance)
