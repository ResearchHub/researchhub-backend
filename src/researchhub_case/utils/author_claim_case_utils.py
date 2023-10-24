import time
import uuid

from django.contrib.admin.options import get_content_type_for_model
from django.db.models import Sum

from mailing_list.lib import base_email_context
from reputation.distributions import Distribution as dist
from reputation.distributions import create_stored_paper_pot
from reputation.distributor import Distributor
from reputation.models import Escrow
from researchhub.settings import BASE_FRONTEND_URL
from utils import sentry
from utils.message import send_email_message


def get_formatted_token():
    return [int(time.time()), uuid.uuid4().hex]


def get_new_validation_token():
    [generated_time, token] = get_formatted_token()
    return [generated_time, token]


def get_client_validation_url(validation_token):
    return BASE_FRONTEND_URL + f"/author-claim-validation/?token={validation_token}"


def get_client_profile_url(author):
    return BASE_FRONTEND_URL + f"/user/{author.id}/overview"


def get_authored_papers_url(author):
    return BASE_FRONTEND_URL + f"/user/{author.id}/authored-papers"


def get_paper_url(paper):
    return BASE_FRONTEND_URL + f"/paper/{paper.id}/{paper.slug}"


def send_validation_email(case):
    validation_token = case.validation_token
    requestor = case.requestor
    requestor_name = f"{requestor.first_name} {requestor.last_name}"
    email_context = {
        **base_email_context,
        "requestor_name": requestor_name,
        "paper_title": case.target_paper.title,
        "paper_url": get_paper_url(case.target_paper),
        "target_author_name": case.target_author_name,
        "validation_url": get_client_validation_url(validation_token),
    }
    send_email_message(
        [case.provided_email],
        "author_claim_validation_email.txt",
        "Please Verify Your Paper Claim",
        email_context,
        "author_claim_validation_email.html",
        "ResearchHub <noreply@researchhub.com>",
    )


def send_approval_email(case, context):
    requestor = case.requestor
    requestor_author = requestor.author_profile
    requestor_name = f"{requestor.first_name} {requestor.last_name}"
    vote_reward = context.get("total_amount_paid", 0)
    email_context = {
        **base_email_context,
        "paper_title": case.target_paper.title,
        "paper_url": get_paper_url(case.target_paper),
        "profile_url": get_client_profile_url(requestor_author),
        "authored_papers_url": get_authored_papers_url(requestor_author),
        "target_author_name": case.target_author_name,
        "requestor_name": requestor_name,
        "vote_reward": vote_reward,
    }
    send_email_message(
        [case.provided_email],
        "author_approval_email.txt",
        "Your paper claim request has been approved",
        email_context,
        "author_approval_email.html",
        "ResearchHub <noreply@researchhub.com>",
    )


def send_rejection_email(case):
    requestor = case.requestor
    requestor_name = f"{requestor.first_name} {requestor.last_name}"
    email_context = {
        **base_email_context,
        "paper_title": case.target_paper.title,
        "paper_url": get_paper_url(case.target_paper),
        "requestor_name": requestor_name,
    }
    send_email_message(
        [case.provided_email],
        "author_rejection_email.txt",
        "Your paper claim request has been denied",
        email_context,
        "author_rejection_email.html",
        "ResearchHub <noreply@researchhub.com>",
    )


def reward_author_claim_case(requestor_author, paper):
    vote_reward = requestor_author.calculate_score()

    author_pot_query = Escrow.objects.filter(
        object_id=paper.id,
        content_type=get_content_type_for_model(paper),
    ).exclude(status=Escrow.PAID)

    # Adding one because that is the requestor user
    total_amount_paid = 0
    author_count = paper.raw_author_count() + 1
    for escrow in author_pot_query.iterator():
        author_pot_amount = (escrow.amount_holding + escrow.amount_paid) / author_count
        escrow.payout(requestor_author.user, author_pot_amount)
        total_amount_paid += author_pot_amount

    try:
        if vote_reward > 0:
            distributor = Distributor(
                dist("REWARD", vote_reward, False),
                requestor_author.user,
                requestor_author,
                time.time(),
            )
            distributor.distribute()
            total_amount_paid += vote_reward
        return total_amount_paid
    except Exception as exception:
        sentry.log_error(exception)
        return total_amount_paid
