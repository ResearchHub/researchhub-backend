import json
import logging
import time
from datetime import datetime, timedelta
from typing import List, Optional

import pytz
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import DurationField, F, Q
from django.db.models.functions import Cast
from web3 import Web3

from ethereum.lib import RSC_CONTRACT_ADDRESS
from hub.models import Hub
from mailing_list.lib import base_email_context
from notification.models import Notification
from reputation.distributions import Distribution as Dist
from reputation.distributor import Distributor
from reputation.lib import check_hotwallet, check_pending_withdrawal, contract_abi
from reputation.models import Bounty, Contribution, Deposit
from reputation.related_models.bounty import AnnotatedBounty
from reputation.related_models.score import Score
from researchhub.celery import QUEUE_CONTRIBUTIONS, app
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import (
    FILTER_BOUNTY_EXPIRED,
    FILTER_BOUNTY_OPEN,
)
from user.models import User
from user.related_models.author_model import Author
from utils.message import send_email_message
from utils.sentry import log_error, log_info
from utils.web3_utils import web3_provider

DEFAULT_REWARD = 1000000

PENDING_TRANSACTION_TTL = 60 * 60 * 1  # 1 hour

logger = logging.getLogger(__name__)


@app.task(queue=QUEUE_CONTRIBUTIONS)
def create_contribution(
    contribution_type, instance_type, user_id, unified_doc_id, object_id
):
    content_type = ContentType.objects.get(**instance_type)
    if contribution_type == Contribution.SUBMITTER:
        create_author_contribution(
            Contribution.AUTHOR, user_id, unified_doc_id, object_id
        )

    previous_contributions = Contribution.objects.filter(
        contribution_type=contribution_type,
        content_type=content_type,
        unified_document_id=unified_doc_id,
    ).order_by("ordinal")

    ordinal = 0
    if previous_contributions.exists():
        ordinal = previous_contributions.last().ordinal + 1

    Contribution.objects.create(
        contribution_type=contribution_type,
        user_id=user_id,
        ordinal=ordinal,
        unified_document_id=unified_doc_id,
        content_type=content_type,
        object_id=object_id,
    )


@app.task(queue=QUEUE_CONTRIBUTIONS)
def create_author_contribution(contribution_type, user_id, unified_doc_id, object_id):
    contributions = []
    content_type = ContentType.objects.get(model="author")
    authors = ResearchhubUnifiedDocument.objects.get(id=unified_doc_id).authors.all()
    for i, author in enumerate(authors.iterator()):
        if author.user:
            user = author.user
            data = {
                "contribution_type": contribution_type,
                "ordinal": i,
                "unified_document_id": unified_doc_id,
                "content_type": content_type,
                "object_id": object_id,
            }

            if user:
                data["user_id"] = user.id

            contributions.append(Contribution(**data))
    Contribution.objects.bulk_create(contributions)


def get_transaction_receipt(transaction_hash, w3):
    # Check if connected successfully
    if not w3.is_connected():
        raise Exception("Failed to connect to Ethereum node.")

    # Get transaction receipt
    return w3.eth.get_transaction_receipt(transaction_hash)


def check_transaction_success(transaction_hash, w3):
    return get_transaction_receipt(transaction_hash, w3)["status"] == 1


def get_transaction(transaction_hash, w3):
    """Get transaction details using provided Web3 instance."""
    # Check if connected successfully
    if not w3.is_connected():
        raise Exception("Failed to connect to Ethereum node.")

    return w3.eth.get_transaction(transaction_hash)


def get_block(block_number, w3):
    """Get block details using provided Web3 instance."""
    # Check if connected successfully
    if not w3.is_connected():
        raise Exception("Failed to connect to Ethereum node.")

    return w3.eth.get_block(block_number)


def get_contract(w3, token_address):
    """Get RSC contract instance using provided Web3 instance and token address."""
    # Check if connected successfully
    if not w3.is_connected():
        raise Exception("Failed to connect to Ethereum node.")

    return w3.eth.contract(
        abi=contract_abi, address=Web3.to_checksum_address(token_address)
    )


def evaluate_transaction(transaction_hash, w3, token_address):
    """Evaluate transaction details using provided Web3 instance."""
    tx = get_transaction(transaction_hash, w3)
    block = get_block(tx["blockNumber"], w3)

    contract = get_contract(w3, token_address)

    func_name, func_params = contract.decode_function_input(tx["input"])
    is_transfer = func_name.fn_name == "transfer"
    is_correct_to_address = func_params["_to"] == settings.WEB3_WALLET_ADDRESS
    block_timestamp = datetime.fromtimestamp(block["timestamp"])
    is_recent_transaction = block_timestamp > datetime.now() - timedelta(
        seconds=PENDING_TRANSACTION_TTL
    )

    return (
        is_transfer and is_correct_to_address and is_recent_transaction,
        func_params["_amount"] / (10**18),  # Convert from smallest denomination
    )


@app.task
def check_deposits():
    logger.info("Starting check deposits task")
    # Sort by created date to ensure a malicious user doesn't attempt to take credit for
    # a deposit made by another user. This is a temporary solution until we add signed messages
    # to validate users own wallets.
    deposits = Deposit.objects.filter(
        Q(paid_status=None) | Q(paid_status="PENDING")
    ).order_by("created_date")

    for deposit in deposits.iterator():
        # If a deposit is not resolved after our set TTL, mark it as failed
        if deposit.created_date < datetime.now(pytz.UTC) - timedelta(
            seconds=PENDING_TRANSACTION_TTL
        ):
            deposit.set_paid_failed()
            continue

        deposit_previously_paid = Deposit.objects.filter(
            transaction_hash=deposit.transaction_hash, paid_status="PAID"
        )
        if deposit_previously_paid.exists():
            deposit.set_paid_failed()
            continue

        user = deposit.user
        try:
            w3_instance = (
                web3_provider.base
                if deposit.network == "BASE"
                else web3_provider.ethereum
            )
            token_address = (
                settings.WEB3_BASE_RSC_ADDRESS
                if deposit.network == "BASE"
                else RSC_CONTRACT_ADDRESS
            )

            transaction_success = check_transaction_success(
                deposit.transaction_hash, w3_instance
            )
            if not transaction_success:
                deposit.set_paid_pending()
                continue

            valid_deposit, deposit_amount = evaluate_transaction(
                deposit.transaction_hash, w3_instance, token_address
            )
            if not valid_deposit:
                deposit.set_paid_failed()
                continue

            with transaction.atomic():
                distribution = Dist("DEPOSIT", deposit_amount, give_rep=False)
                distributor = Distributor(distribution, user, user, time.time(), user)
                distributor.distribute()
                deposit.amount = deposit_amount
                deposit.set_paid()
        except Exception as e:
            log_error(e, "Failed to process deposit")
            deposit.set_paid_pending()

    logger.info("Finished check deposits task")


@app.task
def check_pending_withdrawals():
    logger.info("Starting check pending withdrawals task")
    check_pending_withdrawal()
    logger.info("Starting check pending withdrawals task")


@app.task
def check_hotwallet_balance():
    if settings.PRODUCTION:
        check_hotwallet()


@app.task
def check_open_bounties():
    open_bounties = Bounty.objects.filter(
        status=Bounty.OPEN, parent__isnull=True
    ).annotate(
        time_left=Cast(
            F("expiration_date") - datetime.now(pytz.UTC),
            DurationField(),
        )
    )

    upcoming_expirations = open_bounties.filter(
        time_left__gt=timedelta(days=0), time_left__lte=timedelta(days=1)
    )
    for bounty in upcoming_expirations.iterator():
        # Sends a notification if no notification exists for current bounty
        if not Notification.objects.filter(
            object_id=bounty.id, content_type=ContentType.objects.get_for_model(Bounty)
        ).exists():
            bounty_creator = bounty.created_by
            unified_doc = bounty.unified_document
            notification = Notification.objects.create(
                item=bounty,
                action_user=bounty_creator,
                recipient=bounty_creator,
                unified_document=unified_doc,
                notification_type=Notification.BOUNTY_EXPIRING_SOON,
            )
            notification.send_notification()

            outer_subject = "Your ResearchHub Bounty is Expiring"
            context = {**base_email_context}
            context["action"] = {
                "message": "Your bounty is expiring in one day! \
                If you have a suitable answer, make sure to pay out \
                your bounty in order to keep your reputation on ResearchHub high.",
                "frontend_view_link": unified_doc.frontend_view_link(),
            }
            context["subject"] = "Your Bounty is Expiring"
            send_email_message(
                [bounty_creator.email],
                "general_email_message.txt",
                outer_subject,
                context,
                html_template="general_email_message.html",
            )

    expired_bounties = open_bounties.filter(time_left__lte=timedelta(days=0))
    for bounty in expired_bounties.iterator():
        refund_status = bounty.close(Bounty.EXPIRED)
        bounty.unified_document.update_filters(
            (FILTER_BOUNTY_EXPIRED, FILTER_BOUNTY_OPEN)
        )
        if refund_status is False:
            ids = expired_bounties.values_list("id", flat=True)
            log_info(f"Failed to refund bounties: {ids}")


@app.task
def recalculate_rep_all_users():
    for user in User.objects.iterator():
        try:
            user.calculate_hub_scores()
        except Exception as e:
            print(f"Error calculating rep for user {user.id}: {e}")
            continue


@app.task
def find_qualified_users_and_notify(
    bounty_id: int, target_hubs: List[int], exclude_users: List[int]
) -> List[Notification]:
    """
    Find qualified users for bounty and sends them a notification.
    """
    from django.db.models import IntegerField, OuterRef, Subquery, Value
    from django.db.models.functions import Coalesce

    # Minimum reputation score required to notify a user
    MIN_REP_SCORE_REQUIRED_TO_NOTIFY = 100

    bounty = Bounty.objects.select_related("unified_document").get(id=bounty_id)

    # Get the hub IDs associated with this bounty
    bounty_hub_ids = list(
        set(bounty.unified_document.hubs.values_list("id", flat=True))
    )

    # Combine bounty_hub_ids with explicitly specified target_hubs
    combined_hub_ids = bounty_hub_ids + target_hubs

    # Subquery to get the highest score and corresponding hub_id for each author in the bounty's hubs
    max_score_subquery = (
        Score.objects.filter(author_id=OuterRef("id"), hub_id__in=combined_hub_ids)
        .order_by("-score")
        .values("hub_id", "score")[:1]
    )

    # Get qualified authors and annotate with hub and max score id.
    # For example, if users have multiple matching hubs and score, we annotate with the highest score and hub_id
    qualified_authors = (
        Author.objects.filter(score__hub_id__in=combined_hub_ids)
        .exclude(user_id__isnull=True)  # Exclude authors without a user_id
        .exclude(
            user_id__in=exclude_users
        )  # Exclude specified users such as the one who created the bounty,
        .distinct()
        .annotate(
            max_hub_score=Coalesce(
                Subquery(
                    max_score_subquery.values("score"), output_field=IntegerField()
                ),
                Value(0),
            ),
            matching_hub_id=Subquery(
                max_score_subquery.values("hub_id"), output_field=IntegerField()
            ),
        )
        .filter(
            max_hub_score__gte=MIN_REP_SCORE_REQUIRED_TO_NOTIFY
        )  # Ensure we only get authors with score > MIN_REP_SCORE_REQUIRED_TO_NOTIFY
        .order_by("-max_hub_score")
    )

    notifications_sent = []
    for author in qualified_authors:

        notification = Notification.objects.filter(
            object_id=bounty.id,
            content_type=ContentType.objects.get_for_model(Bounty),
            recipient=author.user,
        )

        if not notification.exists():

            hub = Hub.objects.get(id=author.matching_hub_id)

            notification = Notification.objects.create(
                item=bounty,
                recipient=author.user,
                action_user=author.user,
                unified_document=bounty.unified_document,
                notification_type=Notification.BOUNTY_FOR_YOU,
                extra={
                    "bounty_id": bounty.id,
                    "amount": bounty.amount,
                    "bounty_type": bounty.bounty_type,
                    "bounty_expiration_date": bounty.expiration_date,
                    "user_hub_score": author.max_hub_score,
                    "hub_details": json.dumps({"name": hub.name, "slug": hub.slug}),
                },
            )
            notification.send_notification()
            notifications_sent.append(notification)

    return notifications_sent


@app.task
def find_bounties_for_user_and_notify(user_id) -> Optional[Notification]:
    user = User.objects.get(id=user_id)
    bounties: List[AnnotatedBounty] = Bounty.find_bounties_for_user(user)

    for bounty in bounties:

        notification = Notification.objects.filter(
            object_id=bounty.id,
            content_type=ContentType.objects.get_for_model(Bounty),
            recipient=user,
        )

        if not notification.exists():

            hub = Hub.objects.get(id=bounty.matching_hub_id)

            notification = Notification.objects.create(
                item=bounty,
                recipient=user,
                action_user=user,
                unified_document=bounty.unified_document,
                notification_type=Notification.BOUNTY_FOR_YOU,
                extra={
                    "bounty_id": bounty.id,
                    "amount": bounty.amount,
                    "bounty_type": bounty.bounty_type,
                    "bounty_expiration_date": bounty.expiration_date,
                    "user_hub_score": bounty.user_hub_score,
                    "hub_details": json.dumps({"name": hub.name, "slug": hub.slug}),
                },
            )
            notification.send_notification()
            return notification


@app.task
def recalc_hot_score_for_open_bounties():
    open_bounties = Bounty.objects.filter(status=Bounty.OPEN)

    for bounty in open_bounties:
        bounty.unified_document.calculate_hot_score_v2(should_save=True)
