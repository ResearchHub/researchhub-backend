import time
import uuid

from django.db.models import Count, Q
from paper.models import Vote


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


def reward_author_claim_case(author):
    vote_reward = 0
    papers = author.authored_papers.all()
    for paper in papers.iterator():
        votes = paper.votes.filter(
            created_by__is_suspended=False,
            created_by__probable_spammer=False
        )
        score = votes.aggregate(
            score=Count(
                'id', filter=Q(vote_type=Vote.UPVOTE)
            ) - Count(
                'id', filter=Q(vote_type=Vote.DOWNVOTE)
            )
        ).get('score', 0)
        vote_reward += score

    vote_reward = min(vote_reward, 1000)

    distributor = Distributor(
        dist('REWARD', vote_reward, False),
        author.user,
        author,
        time.time()
    )
    distribution = distributor.distribute()
    return distribution
