import json
import time
import uuid

from utils.message import send_email_message
from mailing_list.lib import base_email_context
from researchhub.settings import BASE_FRONTEND_URL


def get_formatted_token():
    return [int(time.time()), uuid.uuid4().hex]


def get_new_validation_token():
    [generated_time, token] = get_formatted_token()
    return [
        generated_time,
        token
    ]


def get_client_validation_url(validation_token):
    return (
        BASE_FRONTEND_URL
        + f'/author-claim-validation/?token={validation_token}'
    )


def send_validation_email(case):
    # TODO: calvinhlee - add email styling
    validation_token = case.validation_token
    target_author = case.target_author
    requestor = case.requestor
    requestor_name = f'{requestor.first_name} {requestor.last_name}'
    email_context = {
        **base_email_context,
        'author_name': f'{target_author.first_name} {target_author.last_name}',
        'preview_text':  f"{requestor_name}'s Author Claim ",
        'requestor_name': requestor_name,
        'validation_url': get_client_validation_url(validation_token),
    }
    send_email_message(
        [case.provided_email],
        'author_claim_validation_email.txt',
        'Please Verify Your Author Claim',
        email_context,
        'author_claim_validation_email.html',
        'ResearchHub <noreply@researchhub.com>'
    )
