import logging
from datetime import datetime, timedelta
from decimal import Decimal

import pytz
from django.contrib.contenttypes.models import ContentType
from django.db import models

from mailing_list.lib import base_email_context
from notification.models import Notification
from paper.models import Paper
from purchase.circle.service import CircleWalletService
from purchase.models import Fundraise, Purchase, Support
from purchase.related_models.constants.currency import USD
from purchase.services.fundraise_service import FundraiseService
from reputation.models import Deposit
from researchhub.celery import QUEUE_NOTIFICATION, QUEUE_PURCHASES, app
from researchhub.settings import BASE_FRONTEND_URL
from researchhub_document.models import ResearchhubPost
from utils.message import send_email_message
from utils.sentry import log_error, log_info

logger = logging.getLogger(__name__)


@app.task
def update_purchases():
    purchases = Purchase.objects.filter(boost_time__gt=0)
    for purchase in purchases:
        purchase.boost_time = purchase.get_boost_time()
        purchase.save()


@app.task(queue=QUEUE_PURCHASES)
def complete_eligible_fundraises():
    """
    Automatically complete fundraises that have met their goal and are a week old.
    This task checks for OPEN fundraises that:
    1. Have raised funds equal to or greater than their goal amount
    2. Are at least 7 days old (based on start_date)
    3. Have escrow funds available to payout
    """
    log_info("Starting complete_eligible_fundraises task")

    # Calculate the cutoff date (7 days ago)
    cutoff_date = datetime.now(pytz.UTC) - timedelta(days=7)

    # Get all open fundraises that are at least a week old
    eligible_fundraises = Fundraise.objects.filter(
        status=Fundraise.OPEN,
        start_date__lte=cutoff_date,
        escrow__isnull=False,
        escrow__amount_holding__gt=0,
    ).select_related("escrow")

    fundraise_service = FundraiseService()
    completed_count = 0
    error_count = 0

    for fundraise in eligible_fundraises:
        try:
            # Check if the fundraise has met its goal
            amount_raised_usd = fundraise.get_amount_raised(currency=USD)
            goal_amount_usd = float(fundraise.goal_amount)

            if amount_raised_usd >= goal_amount_usd:
                fundraise_service.complete_fundraise(fundraise)
                completed_count += 1
                log_info(f"Successfully completed fundraise {fundraise.id}")

        except Exception as e:
            log_error(e, message=f"Error processing fundraise {fundraise.id}")
            error_count += 1

    log_info(f"Completed {completed_count} fundraises, {error_count} errors")
    return {
        "completed_count": completed_count,
        "error_count": error_count,
        "processed_total": completed_count + error_count,
    }


@app.task(queue=QUEUE_NOTIFICATION)
def send_monthly_preregistration_update_reminders():
    now = datetime.now(pytz.UTC)
    open_fundraises = Fundraise.objects.filter(
        status=Fundraise.OPEN,
    ).exclude(
        end_date__lte=now,
    ).select_related("created_by", "unified_document")

    fundraise_ct = ContentType.objects.get_for_model(Fundraise)
    sent_count = 0

    for fundraise in open_fundraises:
        already_sent = Notification.objects.filter(
            notification_type=Notification.PREREGISTRATION_UPDATE_REMINDER,
            recipient=fundraise.created_by,
            content_type=fundraise_ct,
            object_id=fundraise.id,
            created_date__year=now.year,
            created_date__month=now.month,
        ).exists()

        if already_sent:
            continue

        try:
            notification = Notification.objects.create(
                item=fundraise,
                action_user=fundraise.created_by,
                recipient=fundraise.created_by,
                unified_document=fundraise.unified_document,
                notification_type=Notification.PREREGISTRATION_UPDATE_REMINDER,
            )
            notification.send_notification()
            sent_count += 1
        except Exception as e:
            log_error(e, message=f"Error sending preregistration update reminder for fundraise {fundraise.id}")

    log_info(f"Sent {sent_count} preregistration update reminders")
    return {"sent_count": sent_count}


@app.task(queue=QUEUE_NOTIFICATION)
def send_support_email(
    profile_url,
    sender_name,
    recipient_name,
    email,
    amount,
    date,
    payment_type,
    email_type,
    content_type,
    object_id,
    paper_id=None,
):
    paper_data = {}
    object_supported = "profile"
    if content_type == "paper":
        paper = Paper.objects.get(id=object_id)
        url = f"{BASE_FRONTEND_URL}/paper/{paper.id}/{paper.slug}"
        paper_data["title"] = paper.title
        paper_summary = f"From Paper: {paper.summary}" if paper.summary else ""
        paper_data["summary"] = paper_summary
        paper_data["uploaded_by"] = paper.uploaded_by.full_name()
        paper_data["discussion_count"] = paper.discussion_count
        paper_data["paper_type"] = "".join(paper.paper_type.split("_")).capitalize()
        paper_data["url"] = url
        object_supported = "paper"
    elif content_type == "rhcommentmodel":
        paper = Paper.objects.get(id=paper_id)
        url = f"{BASE_FRONTEND_URL}/paper/{paper.id}/{paper.slug}#comments"
        object_supported = f"""
            <a href="{url}" class="header-link">thread</a>
        """
        object_supported = "thread"
    elif content_type == "thread":
        paper = Paper.objects.get(id=paper_id)
        url = f"{BASE_FRONTEND_URL}/paper/{paper.id}/{paper.slug}#comments"
        object_supported = f"""
            <a href="{url}" class="header-link">thread</a>
        """
        object_supported = "thread"
    elif content_type == "comment":
        paper = Paper.objects.get(id=paper_id)
        url = f"{BASE_FRONTEND_URL}/paper/{paper.id}/{paper.slug}#comments"
        object_supported = f"""
            <a href="{url}" class="header-link">comment</a>
        """
    elif content_type == "reply":
        paper = Paper.objects.get(id=paper_id)
        url = f"{BASE_FRONTEND_URL}/paper/{paper.id}/{paper.slug}#comments"
        object_supported = f"""
            <a href="{url}" class="header-link">reply</a>
        """
    elif content_type == "summary":
        paper = Paper.objects.get(id=paper_id)
        url = f"{BASE_FRONTEND_URL}/paper/{paper.id}/{paper.slug}#summary"
        object_supported = f"""
            <a href="{url}" class="header-link">summary</a>
        """
    elif content_type == "bulletpoint":
        paper = Paper.objects.get(id=paper_id)
        url = f"{BASE_FRONTEND_URL}/paper/{paper.id}/{paper.slug}#takeaways"
        object_supported = f"""
            <a href="{url}" class="header-link">key takeaway</a>
        """
    elif content_type == "researchhubpost":
        post = ResearchhubPost.objects.get(id=object_id)
        url = f"{BASE_FRONTEND_URL}/post/{post.id}/{post.slug}"
        object_supported = f"""
            <a href="{url}" class="header-link">key takeaway</a>
        """

    if payment_type == Support.PAYPAL:
        payment_type = "Paypal"
    elif payment_type == Support.ETH:
        payment_type = "Ethereum"
    elif payment_type == Support.BTC:
        payment_type = "Bitcoin"
    elif payment_type in Support.RSC_ON_CHAIN:
        payment_type = "RSC"
    elif payment_type in Support.RSC_OFF_CHAIN:
        payment_type = "RSC"

    context = {
        **base_email_context,
        "amount": amount,
        "date": date,
        "method": payment_type,
        "email": email,
        "recipient": email_type == "recipient",
        "sender_name": sender_name,
        "recipient_name": recipient_name,
        "paper": paper_data,
        "user_profile": profile_url,
        "object_supported": object_supported,
        "url": url,
    }

    if email_type == "sender":
        subject = "Receipt From ResearchHub"
        send_email_message(
            email,
            "support_receipt.txt",
            subject,
            context,
            html_template="support_receipt.html",
        )
    elif email_type == "recipient":
        subject = "Someone Sent You RSC on ResearchHub!"
        send_email_message(
            email,
            "support_receipt.txt",
            subject,
            context,
            html_template="support_receipt.html",
        )


@app.task(
    bind=True,
    queue=QUEUE_PURCHASES,
    max_retries=3,
    default_retry_delay=60,
)
def sweep_deposit_to_multisig(self, circle_wallet_id, amount, network, sweep_reference):
    """
    Sweep deposited RSC from a user's Circle wallet.

    Amounts worth >= $10,000 USD are sent to the multisig wallet;
    smaller amounts are sent to the hot wallet.

    Fired asynchronously after crediting a user's balance on deposit.
    Updates Deposit.sweep_status to track the outcome.
    """
    deposit = Deposit.objects.filter(circle_notification_id=sweep_reference).first()

    try:
        service = CircleWalletService()
        result = service.sweep_wallet(
            circle_wallet_id=circle_wallet_id,
            amount=amount,
            network=network,
            sweep_reference=sweep_reference,
        )
        if deposit:
            deposit.sweep_status = Deposit.SWEEP_INITIATED
            deposit.sweep_transfer_id = result.transfer_id
            deposit.save(update_fields=["sweep_status", "sweep_transfer_id"])
    except ValueError:
        logger.exception(
            "Sweep failed (not retryable): circle_wallet_id=%s amount=%s "
            "network=%s sweep_reference=%s",
            circle_wallet_id,
            amount,
            network,
            sweep_reference,
        )
        if deposit:
            deposit.sweep_status = Deposit.SWEEP_FAILED
            deposit.save(update_fields=["sweep_status"])
        raise
    except Exception as exc:
        logger.exception(
            "Sweep failed (retrying): circle_wallet_id=%s amount=%s "
            "network=%s sweep_reference=%s",
            circle_wallet_id,
            amount,
            network,
            sweep_reference,
        )
        if deposit and self.request.retries >= self.max_retries:
            deposit.sweep_status = Deposit.SWEEP_FAILED
            deposit.save(update_fields=["sweep_status"])
        raise self.retry(exc=exc)


STALE_SWEEP_SECONDS = 60 * 60  # 1 hour


@app.task(queue=QUEUE_PURCHASES)
def retry_failed_sweeps():
    """
    Hourly task to retry sweeps that failed or appear stuck.

    Picks up Circle deposits where:
    - sweep_status=FAILED (exhausted Celery retries or Circle reported failure)
    - sweep_status=INITIATED and updated_date is older than STALE_SWEEP_SECONDS
      (sweep was accepted by Circle but never confirmed via outbound webhook)

    For each, resets to PENDING and re-dispatches sweep_deposit_to_multisig.
    """
    stale_cutoff = datetime.now(pytz.UTC) - timedelta(seconds=STALE_SWEEP_SECONDS)

    retryable_deposits = (
        Deposit.objects.filter(
            circle_notification_id__isnull=False,
        )
        .filter(
            models.Q(sweep_status=Deposit.SWEEP_FAILED)
            | models.Q(
                sweep_status=Deposit.SWEEP_INITIATED,
                updated_date__lt=stale_cutoff,
            )
        )
        .select_related("user__wallet")
    )

    retried = 0
    for deposit in retryable_deposits:
        wallet = getattr(deposit.user, "wallet", None)
        if not wallet or not wallet.circle_wallet_id:
            logger.warning(
                "Cannot retry sweep for deposit %s — no Circle wallet",
                deposit.id,
            )
            continue

        deposit.sweep_status = Deposit.SWEEP_PENDING
        deposit.save(update_fields=["sweep_status"])

        sweep_deposit_to_multisig.delay(
            circle_wallet_id=wallet.circle_wallet_id,
            amount=deposit.amount,
            network=deposit.network,
            sweep_reference=deposit.circle_notification_id,
        )
        retried += 1

    logger.info("retry_failed_sweeps: re-dispatched %d sweeps", retried)
    return retried
