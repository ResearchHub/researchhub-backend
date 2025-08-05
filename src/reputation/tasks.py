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
from ethereum.lib import (
    RSC_CONTRACT_ADDRESS,
    execute_erc20_transfer,
    get_gas_estimate,
    get_private_key,
)
from hub.models import Hub
from mailing_list.lib import base_email_context
from notification.models import Notification
from reputation.distributions import Distribution as Dist
from reputation.distributor import Distributor
from reputation.lib import check_hotwallet, check_pending_withdrawal, contract_abi
from reputation.models import Bounty, Contribution, Deposit
from reputation.related_models.bounty import AnnotatedBounty
from reputation.related_models.score import Score
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

    Returns:
        tuple: (is_valid_and_recent, deposit_amount)
            - is_valid_and_recent: Boolean indicating if transaction is valid and recent
            - deposit_amount: Amount transferred in human-readable format (not wei)
    """
    tx = get_transaction(transaction_hash, w3)
    block = get_block(tx["blockNumber"], w3)
    receipt = get_transaction_receipt(transaction_hash, w3)

    contract = get_contract(w3, token_address)

    block_timestamp = datetime.fromtimestamp(block["timestamp"])
    is_recent_transaction = block_timestamp > datetime.now() - timedelta(
        seconds=PENDING_TRANSACTION_TTL
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
def check_deposits():
    key = lock.name("check_deposits")
    if not lock.acquire(key):
        logger.warning(f"Already locked {key}, skipping task")
        return False

    try:
        _check_deposits()
    finally:
        lock.release(key)
        logger.info(f"Released lock {key}")


def _check_deposits():
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
    open_bounties = Bounty.objects.filter(status=Bounty.OPEN)

    for bounty in open_bounties:
        bounty.unified_document.calculate_hot_score(should_save=True)


NULL_ADDRESS = "0x0000000000000000000000000000000000000000"


@app.task(queue=QUEUE_PURCHASES)
def burn_revenue_rsc(network="ETHEREUM"):
    """
    Weekly task to burn ResearchCoin from the revenue account.

    This task:
    1. Gets the current balance of revenue1@researchhub.foundation
    2. Creates negative balance records to zero out the account
    3. Transfers the same amount from hot wallet to null address (burning)
    Args:
        network: "ETHEREUM" or "BASE" - which network to burn on
    """
    log_info(f"Starting weekly RSC burning task on {network}")

    try:
        # Get the revenue account
        revenue_account = User.objects.get_community_revenue_account()

        # Get current balance (excluding locked funds)
        current_balance = revenue_account.get_balance()

        if current_balance <= 0:
            log_info(f"Revenue account has no balance to burn: {current_balance}")
            return

        log_info(f"Revenue account balance to burn: {current_balance}")

        # Step 1: Create negative balance records to zero out the account
        _zero_out_revenue_account(revenue_account, current_balance)

        # Step 2: Burn tokens from hot wallet
        _burn_tokens_from_hot_wallet(current_balance, network)

        log_info(
            f"Successfully burned {current_balance} RSC from revenue account on {network}"
        )

    except Exception as e:
        log_error(e, f"Failed to burn revenue RSC on {network}")
        raise


def _zero_out_revenue_account(revenue_account, amount):
    """
    Creates negative balance records to zero out the revenue account.
    """
    from reputation.distributions import Distribution

    # Create a distribution for the burning operation
    distribution = Distribution("RSC_BURN", -amount, give_rep=False)

    # Use the revenue account as both recipient and giver
    distributor = Distributor(
        distribution, revenue_account, revenue_account, time.time(), revenue_account
    )

    # This will create a negative balance record
    distributor.distribute()


def _burn_tokens_from_hot_wallet(amount, network="ETHEREUM"):
    """
    Transfers tokens from hot wallet to null address (burning them).
    """
    try:
        # Get the appropriate web3 provider and contract address
        if network == "BASE":
            w3 = web3_provider.base
            contract_address = settings.WEB3_BASE_RSC_ADDRESS
        else:
            w3 = web3_provider.ethereum
            contract_address = RSC_CONTRACT_ADDRESS

        contract = w3.eth.contract(
            abi=contract_abi, address=Web3.to_checksum_address(contract_address)
        )

        # Estimate gas cost before proceeding
        gas_estimate = get_gas_estimate(
            contract.functions.transfer(NULL_ADDRESS, int(amount * 10**18))
        )
        gas_price = w3.eth.generate_gas_price()
        estimated_cost_wei = gas_estimate * gas_price
        estimated_cost_eth = estimated_cost_wei / 10**18

        log_info(
            f"Estimated gas cost for burning {amount} RSC: {estimated_cost_eth} ETH"
        )

        # Check hot wallet ETH balance
        eth_balance = w3.eth.get_balance(settings.WEB3_WALLET_ADDRESS)
        eth_balance_eth = eth_balance / 10**18

        if eth_balance < estimated_cost_wei * 1.2:  # 20% buffer
            error_msg = f"Insufficient ETH in hot wallet. Need ~{estimated_cost_eth} ETH, have {eth_balance_eth} ETH"
            log_error(Exception(error_msg), error_msg)
            raise Exception(error_msg)

        # Execute the transfer to null address
        tx_hash = execute_erc20_transfer(
            w3=w3,
            sender=settings.WEB3_WALLET_ADDRESS,
            sender_signing_key=get_private_key(),
            contract=contract,
            to=NULL_ADDRESS,
            amount=amount,
            network="ETHEREUM",
        )

        log_info(f"Burning transaction submitted: {tx_hash}")
        return tx_hash

    except Exception as e:
        log_error(e, f"Failed to burn {amount} RSC from hot wallet")
        raise


@app.task(queue=QUEUE_PURCHASES)
def check_hot_wallet_health():
    """
    Check if hot wallet has sufficient funds for operations.
    """
    try:
        # Check Ethereum mainnet
        eth_w3 = web3_provider.ethereum
        eth_balance = eth_w3.eth.get_balance(settings.WEB3_WALLET_ADDRESS)
        eth_balance_eth = eth_balance / 10**18

        eth_contract = eth_w3.eth.contract(
            abi=contract_abi, address=Web3.to_checksum_address(RSC_CONTRACT_ADDRESS)
        )
        eth_rsc_balance = eth_contract.functions.balanceOf(
            settings.WEB3_WALLET_ADDRESS
        ).call()
        eth_rsc_balance_human = eth_rsc_balance / 10**18

        # Check Base network
        base_w3 = web3_provider.base
        base_balance = base_w3.eth.get_balance(settings.WEB3_WALLET_ADDRESS)
        base_balance_eth = base_balance / 10**18

        base_contract = base_w3.eth.contract(
            abi=contract_abi,
            address=Web3.to_checksum_address(settings.WEB3_BASE_RSC_ADDRESS),
        )
        base_rsc_balance = base_contract.functions.balanceOf(
            settings.WEB3_WALLET_ADDRESS
        ).call()
        base_rsc_balance_human = base_rsc_balance / 10**18

        log_info(
            f"Hot wallet health check - ETH: {eth_balance_eth:.4f} ETH, {eth_rsc_balance_human:.2f} RSC | Base: {base_balance_eth:.4f} ETH, {base_rsc_balance_human:.2f} RSC"
        )

        # Alert if balances are low
        if eth_balance_eth < 0.1:  # Less than 0.1 ETH
            log_error(
                Exception("Low ETH balance"),
                f"Hot wallet ETH balance is low: {eth_balance_eth} ETH",
            )

        if base_balance_eth < 0.01:  # Less than 0.01 ETH on Base
            log_error(
                Exception("Low Base ETH balance"),
                f"Hot wallet Base ETH balance is low: {base_balance_eth} ETH",
            )

    except Exception as e:
        log_error(e, "Failed to check hot wallet health")
