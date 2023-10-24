import json

from boto3.session import Session

from researchhub.celery import QUEUE_AUTHOR_CLAIM, app
from researchhub.settings import (
    AWS_ACCESS_KEY_ID,
    AWS_S3_REGION_NAME,
    AWS_SCHOLARLY_LAMBDA,
    AWS_SECRET_ACCESS_KEY,
)
from researchhub_case.constants.case_constants import APPROVED, DENIED, INITIATED
from researchhub_case.models import AuthorClaimCase
from researchhub_case.utils.author_claim_case_utils import (
    get_new_validation_token,
    reward_author_claim_case,
    send_approval_email,
    send_rejection_email,
    send_validation_email,
)
from researchhub_document.related_models.constants.document_type import (
    FILTER_AUTHOR_CLAIMED,
)
from rh_scholarly.lambda_handler import AUTHOR_PROFILE_LOOKUP
from user.models import Author, AuthorCitation
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
            print("exception", exception)
            sentry.log_error(exception)


@app.task(queue=QUEUE_AUTHOR_CLAIM)
def after_approval_flow(case_id):
    instance = AuthorClaimCase.objects.get(id=case_id)
    if instance.status == APPROVED:
        try:
            requestor_author = instance.requestor.author_profile

            total_amount_paid = reward_author_claim_case(
                requestor_author, instance.target_paper
            )
            if instance.target_paper is None:
                raise Exception("Cannot approve claim because paper was not found")

            send_approval_email(
                instance, context={"total_amount_paid": total_amount_paid}
            )
            instance.target_paper.unified_document.update_filter(FILTER_AUTHOR_CLAIMED)
        except Exception as exception:
            sentry.log_error(exception)


@app.task(queue=QUEUE_AUTHOR_CLAIM)
def after_rejection_flow(
    case_id,
    notify_user=False,
):
    instance = AuthorClaimCase.objects.get(id=case_id)
    if instance.status == DENIED and notify_user is True:
        send_rejection_email(instance)


@app.task(queue=QUEUE_AUTHOR_CLAIM)
def celery_add_author_citations(author_profile_id, google_scholar_id):
    lambda_body = {AUTHOR_PROFILE_LOOKUP: [google_scholar_id]}
    data_bytes = json.dumps(lambda_body)
    session = Session(
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        region_name=AWS_S3_REGION_NAME,
    )
    lambda_client = session.client(
        service_name="lambda", region_name=AWS_S3_REGION_NAME
    )
    response = lambda_client.invoke(
        FunctionName=AWS_SCHOLARLY_LAMBDA,
        InvocationType="RequestResponse",
        Payload=data_bytes,
    )
    response_data = response.get("Payload", None)
    if response_data is None:
        return False

    response_data = json.loads(response_data.read())
    h_index = response_data.get("hindex", 0)
    publications = response_data.get("publications", [])

    author = Author.objects.get(id=author_profile_id)
    author.h_index = h_index

    author_citations = [
        AuthorCitation(
            author=author,
            citation_count=publication.get("num_citations", 0),
            citation_name=publication.get("bib", {}).get("citation", ""),
            cited_by_url=publication.get("citedby_url", None),
            publish_year=publication.get("bib", {}).get("pub_year", "0000"),
            title=publication.get("bib", {}).get("title", ""),
        )
        for publication in publications
    ]
    AuthorCitation.objects.bulk_create(author_citations)
    author.save()
