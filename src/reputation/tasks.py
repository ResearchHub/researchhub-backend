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

import utils.locking as lock
from ethereum.lib import RSC_CONTRACT_ADDRESS
from hub.models import Hub
from mailing_list.lib import base_email_context
from notification.models import Notification
from reputation.constants.bounty import ASSESSMENT_PERIOD_DAYS
from reputation.distributions import Distribution as Dist
from reputation.distributor import Distributor
from reputation.lib import check_hotwallet, check_pending_withdrawal, contract_abi
from reputation.models import Bounty, BountySolution, Contribution, Deposit
from reputation.related_models.bounty import AnnotatedBounty
from reputation.related_models.score import Score
from reputation.services.wallet import WalletService
from researchhub.celery import QUEUE_CONTRIBUTIONS, QUEUE_PURCHASES, app
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

PENDING_TRANSACTION_MAX_AGE = 60 * 60 * 1  # 1 hour

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


def evaluate_transaction(transaction_hash, w3, token_address, max_age=None):
    """
    Evaluate transaction details using provided Web3 instance.

    This function analyzes ERC20 token transactions by examining the transaction logs
    rather than the transaction input. This approach supports both:
    1. Direct calls to ERC20 contracts (traditional wallets)
    2. Smart wallet transactions where the ERC20 transfer happens through
       internal transactions logged as events

    Smart wallets (like Coinbase Smart Wallet, Safe, etc.) execute transactions
    through their own contract logic, so the actual ERC20 transfer appears in the
    transaction logs as Transfer events, not in the main transaction input.

    Args:
        transaction_hash: The hash of the transaction to evaluate
        w3: Web3 instance connected to the blockchain
        token_address: Address of the ERC20 token contract
        max_age: Optional max age in seconds. Defaults to PENDING_TRANSACTION_MAX_AGE if not provided

    Returns:
        tuple: (is_valid_and_recent, deposit_amount)
            - is_valid_and_recent: Boolean indicating if transaction is valid and recent
            - deposit_amount: Amount transferred in human-readable format (not wei)
    """
    if max_age is None:
        max_age = PENDING_TRANSACTION_MAX_AGE

    tx = get_transaction(transaction_hash, w3)
    block = get_block(tx["blockNumber"], w3)
    receipt = get_transaction_receipt(transaction_hash, w3)

    contract = get_contract(w3, token_address)

    block_timestamp = datetime.fromtimestamp(block["timestamp"])
    is_recent_transaction = block_timestamp > datetime.now() - timedelta(
        seconds=max_age
    )

    # Look for Transfer events in the transaction logs
    # This approach supports both direct calls and smart wallet transactions
    transfer_events = []
    for log_entry in receipt["logs"]:
        try:
            # Check if this log is from our token contract
            if (
                log_entry.address.lower()
                == Web3.to_checksum_address(token_address).lower()
            ):
                # Try to decode the log as a Transfer event
                decoded_log = contract.events.Transfer().process_log(log_entry)
                transfer_events.append(decoded_log)
        except Exception:
            # Skip logs that can't be decoded as Transfer events
            continue

    # Find transfers to our wallet address
    valid_transfers = []
    for event in transfer_events:
        if event.args.get("_to", "").lower() == settings.WEB3_WALLET_ADDRESS.lower():
            valid_transfers.append(event)

    if not valid_transfers:
        return False, 0

    # Sum up all valid transfers (in case there are multiple in one transaction)
    total_amount = sum(event.args.get("_amount", 0) for event in valid_transfers)

    # Convert from smallest denomination (wei equivalent)
    deposit_amount = total_amount / (10**18)

    return is_recent_transaction and len(valid_transfers) > 0, deposit_amount


@app.task
def check_deposits(max_age=None):
    key = lock.name("check_deposits")
    if not lock.acquire(key):
        logger.warning(f"Already locked {key}, skipping task")
        return False

    try:
        _check_deposits(max_age=max_age)
    finally:
        lock.release(key)
        logger.info(f"Released lock {key}")


def _check_deposits(max_age=None):
    if max_age is None:
        max_age = PENDING_TRANSACTION_MAX_AGE

    logger.info("Starting check deposits task")
    # Sort by created date to ensure a malicious user doesn't attempt to take
    # credit for a deposit made by another user. This is a temporary solution
    # until we add signed messages to validate users own wallets.
    deposits = Deposit.objects.filter(
        Q(paid_status=None) | Q(paid_status="PENDING")
    ).order_by("created_date")

    for deposit in deposits.iterator():
        with transaction.atomic():
            # Add a db lock on the deposit to prevent race conditions
            deposit = Deposit.objects.select_for_update().get(id=deposit.id)

            # If a deposit is not resolved after our set TTL, mark it as failed
            if deposit.created_date < datetime.now(pytz.UTC) - timedelta(
                seconds=max_age
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
                    deposit.transaction_hash, w3_instance, token_address, max_age
                )
                if not valid_deposit:
                    deposit.set_paid_failed()
                    continue

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
    key = lock.name("check_pending_withdrawals")
    if not lock.acquire(key):
        logger.warning(f"Already locked {key}, skipping task")
        return False

    try:
        check_pending_withdrawal()
    finally:
        lock.release(key)
        logger.info(f"Released lock {key}")


@app.task
def check_hotwallet_balance():
    if settings.PRODUCTION:
        check_hotwallet()


@app.task
def check_open_bounties():
    now = datetime.now(pytz.UTC)

    open_bounties = Bounty.objects.filter(
        status=Bounty.OPEN, parent__isnull=True
    ).annotate(
        time_left=Cast(
            F("expiration_date") - now,
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

            outer_subject = "Your ResearchHub Bounty Submission Period Ending"
            context = {**base_email_context}
            context["action"] = {
                "message": f"Your bounty submission period is ending in 24 hours. \
                After that, no new reviews will be submitted. You'll have {ASSESSMENT_PERIOD_DAYS} days \
                to review and award the best solutions.",
                "frontend_view_link": unified_doc.frontend_view_link(),
            }
            context["subject"] = "Bounty Submission Period Ending Soon"
            send_email_message(
                [bounty_creator.email],
                "general_email_message.txt",
                outer_subject,
                context,
                html_template="general_email_message.html",
            )

    # Transition OPEN -> ASSESSMENT when expiration_date passes
    expired_open_bounties = open_bounties.filter(time_left__lte=timedelta(days=0))
    for bounty in expired_open_bounties.iterator():
        # Set assessment_end_date to ASSESSMENT_PERIOD_DAYS from now
        assessment_end_date = now + timedelta(days=ASSESSMENT_PERIOD_DAYS)
        bounty.assessment_end_date = assessment_end_date
        bounty.set_assessment_status()
        bounty.unified_document.update_filters((FILTER_BOUNTY_OPEN,))

        # Notify creator that bounty entered assessment phase
        bounty_creator = bounty.created_by
        unified_doc = bounty.unified_document
        creator_notification = Notification.objects.create(
            item=bounty,
            action_user=bounty_creator,
            recipient=bounty_creator,
            unified_document=unified_doc,
            notification_type=Notification.BOUNTY_ENTERED_ASSESSMENT,
        )
        creator_notification.send_notification()

        outer_subject = "Your ResearchHub Bounty Entered Assessment Phase"
        context = {**base_email_context}
        context["action"] = {
            "message": f"Submission period has ended. No new peer reviews will be submitted. \
            You have {ASSESSMENT_PERIOD_DAYS} days to review and award the best solutions.",
            "frontend_view_link": unified_doc.frontend_view_link(),
        }
        context["subject"] = "Bounty Entered Assessment Phase"
        send_email_message(
            [bounty_creator.email],
            "general_email_message.txt",
            outer_subject,
            context,
            html_template="general_email_message.html",
        )

        # Notify reviewers who submitted solutions
        submitted_solutions = (
            BountySolution.objects.filter(
                bounty=bounty, status=BountySolution.Status.SUBMITTED
            )
            .select_related("created_by")
            .values_list("created_by", flat=True)
            .distinct()
        )

        for reviewer_id in submitted_solutions:
            reviewer = User.objects.get(id=reviewer_id)
            # Check if notification already exists to avoid duplicates
            if not Notification.objects.filter(
                object_id=bounty.id,
                content_type=ContentType.objects.get_for_model(Bounty),
                recipient=reviewer,
                notification_type=Notification.BOUNTY_SOLUTION_IN_ASSESSMENT,
            ).exists():
                reviewer_notification = Notification.objects.create(
                    item=bounty,
                    action_user=bounty_creator,
                    recipient=reviewer,
                    unified_document=unified_doc,
                    notification_type=Notification.BOUNTY_SOLUTION_IN_ASSESSMENT,
                )
                reviewer_notification.send_notification()

    # Handle ASSESSMENT bounties: transition to EXPIRED when assessment_end_date passes
    assessment_bounties = Bounty.objects.filter(
        status=Bounty.ASSESSMENT, parent__isnull=True
    ).annotate(
        assessment_time_left=Cast(
            F("assessment_end_date") - now,
            DurationField(),
        )
    )

    # Notify creator 24 hours before assessment period ends
    upcoming_assessment_expirations = assessment_bounties.filter(
        assessment_time_left__gt=timedelta(days=0),
        assessment_time_left__lte=timedelta(days=1),
    )
    for bounty in upcoming_assessment_expirations.iterator():
        # Check if notification already exists to avoid duplicates
        if not Notification.objects.filter(
            object_id=bounty.id,
            content_type=ContentType.objects.get_for_model(Bounty),
            notification_type=Notification.BOUNTY_ASSESSMENT_EXPIRING_SOON,
        ).exists():
            bounty_creator = bounty.created_by
            unified_doc = bounty.unified_document
            notification = Notification.objects.create(
                item=bounty,
                action_user=bounty_creator,
                recipient=bounty_creator,
                unified_document=unified_doc,
                notification_type=Notification.BOUNTY_ASSESSMENT_EXPIRING_SOON,
            )
            notification.send_notification()

            outer_subject = "Your ResearchHub Bounty Assessment Period Ending"
            context = {**base_email_context}
            context["action"] = {
                "message": "Assessment period ending in 24 hours. Award solutions now \
                or remaining funds will be refunded.",
                "frontend_view_link": unified_doc.frontend_view_link(),
            }
            context["subject"] = "Bounty Assessment Period Ending Soon"
            send_email_message(
                [bounty_creator.email],
                "general_email_message.txt",
                outer_subject,
                context,
                html_template="general_email_message.html",
            )

    expired_assessment_bounties = assessment_bounties.filter(
        assessment_time_left__lte=timedelta(days=0)
    )
    for bounty in expired_assessment_bounties.iterator():
        refund_status = bounty.close(Bounty.EXPIRED)
        bounty.unified_document.update_filters(
            (FILTER_BOUNTY_EXPIRED, FILTER_BOUNTY_OPEN)
        )
        if refund_status is False:
            ids = expired_assessment_bounties.values_list("id", flat=True)
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

    # Subquery to get the highest score and corresponding hub_id for each
    # author in the bounty's hubs
    max_score_subquery = (
        Score.objects.filter(author_id=OuterRef("id"), hub_id__in=combined_hub_ids)
        .order_by("-score")
        .values("hub_id", "score")[:1]
    )

    # Get qualified authors and annotate with hub and max score id.
    # For example, if users have multiple matching hubs and score, we annotate
    # with the highest score and hub_id
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
    open_bounties = Bounty.objects.filter(status__in=(Bounty.OPEN, Bounty.ASSESSMENT))

    for bounty in open_bounties:
        bounty.unified_document.calculate_hot_score(should_save=True)


@app.task(queue=QUEUE_PURCHASES)
def burn_revenue_rsc(network="BASE"):
    """
    Weekly task to burn ResearchCoin from the revenue account.
    """
    return WalletService.burn_revenue_rsc(network)
