import json
import time
from datetime import datetime, timedelta

import pytz
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import DurationField, F, Q
from django.db.models.functions import Cast
from web3 import Web3

from ethereum.lib import RSC_CONTRACT_ADDRESS
from mailing_list.lib import base_email_context
from notification.models import Notification
from reputation.distributions import Distribution as Dist
from reputation.distributor import Distributor
from reputation.lib import check_hotwallet, check_pending_withdrawal, contract_abi
from reputation.models import Bounty, Contribution, Deposit
from researchhub.celery import QUEUE_CONTRIBUTIONS, app
from researchhub.settings import PRODUCTION, WEB3_WALLET_ADDRESS, w3
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import (
    ALL,
    BOUNTY,
    FILTER_BOUNTY_EXPIRED,
    FILTER_BOUNTY_OPEN,
)
from researchhub_document.utils import reset_unified_document_cache
from user.models import User
from utils.message import send_email_message
from utils.sentry import log_error, log_info

DEFAULT_REWARD = 1000000

PENDING_TRANSACTION_TTL = 60 * 60 * 1  # 1 hour


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
def delete_contribution(contribution_type, instance_type, unified_doc_id, object_id):
    content_type = ContentType.objects.get(**instance_type)
    contribution = Contribution.objects.filter(
        contribution_type=contribution_type,
        content_type=content_type,
        unified_document_id=unified_doc_id,
        object_id=object_id,
    )

    # ignore if there's more than one contribution
    if contribution.count() > 1:
        return

    if contribution.exists():
        contribution.delete()


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


def get_transaction_receipt(transaction_hash):
    # Check if connected successfully
    if not w3.is_connected():
        raise Exception("Failed to connect to Ethereum node.")

    # Get transaction receipt
    return w3.eth.get_transaction_receipt(transaction_hash)


def check_transaction_success(transaction_hash):
    return get_transaction_receipt(transaction_hash)["status"] == 1


def get_transaction(transaction_hash):
    # Check if connected successfully
    if not w3.is_connected():
        raise Exception("Failed to connect to Ethereum node.")

    return w3.eth.get_transaction(transaction_hash)


def get_block(block_number):
    # Check if connected successfully
    if not w3.is_connected():
        raise Exception("Failed to connect to Ethereum node.")

    return w3.eth.get_block(block_number)


def get_contract():
    # Check if connected successfully
    if not w3.is_connected():
        raise Exception("Failed to connect to Ethereum node.")

    return w3.eth.contract(
        abi=contract_abi, address=Web3.to_checksum_address(RSC_CONTRACT_ADDRESS)
    )


def evaluate_transaction(transaction_hash):
    tx = get_transaction(transaction_hash)
    block = get_block(tx["blockNumber"])

    contract = get_contract()

    func_name, func_params = contract.decode_function_input(tx["input"])
    is_transfer = func_name.fn_name == "transfer"
    is_correct_to_address = func_params["_to"] == WEB3_WALLET_ADDRESS
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
    print("Checking deposits at: ", time.time())
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
            transaction_success = check_transaction_success(deposit.transaction_hash)
            if not transaction_success:
                deposit.set_paid_pending()
                continue

            valid_deposit, deposit_amount = evaluate_transaction(
                deposit.transaction_hash
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


@app.task
def check_pending_withdrawals():
    check_pending_withdrawal()


@app.task
def check_hotwallet_balance():
    if PRODUCTION:
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

    reset_unified_document_cache(
        document_type=[ALL.lower(), BOUNTY.lower()],
    )


@app.task
def send_bounty_hub_notifications():
    action_user = User.objects.get_community_account()
    open_bounties = Bounty.objects.filter(
        status=Bounty.OPEN,
    ).annotate(
        time_left=Cast(
            F("expiration_date") - datetime.now(pytz.UTC),
            DurationField(),
        )
    )

    upcoming_expirations = open_bounties.filter(
        time_left__gt=timedelta(days=0), time_left__lte=timedelta(days=5)
    )
    for bounty in upcoming_expirations.iterator():
        hubs = bounty.unified_document.hubs.all()
        for hub in hubs.iterator():
            for subscriber in hub.subscribers.all().iterator():
                # Sends a notification if no notification exists for user in hub with current bounty
                if not Notification.objects.filter(
                    object_id=bounty.id,
                    content_type=ContentType.objects.get_for_model(Bounty),
                    recipient=subscriber,
                    action_user=action_user,
                ).exists():
                    bounty_item = bounty.item
                    if isinstance(bounty_item, ResearchhubUnifiedDocument):
                        unified_doc = bounty_item
                    else:
                        unified_doc = bounty_item.unified_document
                    notification = Notification.objects.create(
                        item=bounty,
                        action_user=action_user,
                        recipient=subscriber,
                        unified_document=unified_doc,
                        notification_type=Notification.BOUNTY_HUB_EXPIRING_SOON,
                        extra={
                            "hub_details": json.dumps(
                                {"name": hub.name, "slug": hub.slug}
                            )
                        },
                    )
                    notification.send_notification()


@app.task
def recalc_hot_score_for_open_bounties():
    open_bounties = Bounty.objects.filter(status=Bounty.OPEN)

    for bounty in open_bounties:
        bounty.unified_document.calculate_hot_score_v2(should_save=True)
