import time
import uuid

from utils import sentry

from reputation.distributions import Distribution as dist
from reputation.distributor import Distributor
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

def get_client_profile_url(author):
    return (
        BASE_FRONTEND_URL
        + f'/user/{author.id}/overview'
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

def send_approval_email(case):
    target_author = case.target_author
    requestor = case.requestor
    requestor_author = requestor.author_profile
    vote_reward = requestor_author.calculate_score()
    requestor_name = f'{requestor.first_name} {requestor.last_name}'
    target_author_name = f'{target_author.first_name} {target_author.last_name}'
    email_context = {
        **base_email_context,
        'author_name': f'{target_author.first_name} {target_author.last_name}',
        'preview_text':  f"{requestor_name}'s Author Claim ",
        'requestor_name': requestor_name,
        'target_author_name': target_author_name,
        'profile_url': get_client_profile_url(requestor_author),
        'vote_reward': vote_reward,
    }
    send_email_message(
        [case.provided_email],
        'author_approval_email.txt',
        'Your author claim request has been approved',
        email_context,
        'author_approval_email.html',
        'ResearchHub <noreply@researchhub.com>'
    )

def send_rejection_email(case):
    target_author = case.target_author
    requestor = case.requestor
    requestor_name = f'{requestor.first_name} {requestor.last_name}'
    target_author_name = f'{target_author.first_name} {target_author.last_name}'
    email_context = {
        **base_email_context,
        'author_name': f'{target_author.first_name} {target_author.last_name}',
        'preview_text':  f"{requestor_name}'s Author Claim ",
        'target_author_name': target_author_name,
        'requestor_name': requestor_name,
        'target_author': target_author,
    }
    send_email_message(
        [case.provided_email],
        'author_rejection_email.txt',
        'Your author claim request has been denied',
        email_context,
        'author_rejection_email.html',
        'ResearchHub <noreply@researchhub.com>'
    )


def reward_author_claim_case(requestor_author, target_author_papers):
    vote_reward = requestor_author.calculate_score()
    try:
        distributor = Distributor(
            dist('REWARD', vote_reward, False),
            requestor_author.user,
            requestor_author,
            time.time()
        )
        distribution = distributor.distribute()
        return distribution
    except Exception as exception:
        print("reward_author_claim_case: ", exception)
        sentry.log_error(exception)
