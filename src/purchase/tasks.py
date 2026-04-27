import logging
from datetime import datetime, timedelta

import pytz
from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from mailing_list.lib import base_email_context, send_email
from notification.models import Notification
from paper.models import Paper
from purchase.circle.service import CircleWalletService
from purchase.models import Fundraise, Purchase, RscExchangeRate, Support
from purchase.related_models.constants.currency import USD
from purchase.services.fundraise_service import FundraiseService
from reputation.models import Deposit
from researchhub.celery import QUEUE_NOTIFICATION, QUEUE_PURCHASES, app
from researchhub.settings import BASE_FRONTEND_URL
from researchhub_document.models import ResearchhubPost
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

    # Use the trailing 3-day average RSC→USD rate so a transient price spike
    # on the closeout day can't push a fundraise past its USD goal.
    average_rsc_usd_rate = RscExchangeRate.get_average_rate(days=3)

    for fundraise in eligible_fundraises:
        try:
            # Check if the fundraise has met its goal
            amount_raised_usd = fundraise.get_amount_raised(
                currency=USD, rsc_to_usd_rate=average_rsc_usd_rate
            )
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

    # Get distinct (author, unified_document) pairs with completed fundraises.
    # We send at most one reminder per author per document per month.
    completed_fundraises = (
        Fundraise.objects.filter(status=Fundraise.COMPLETED)
        .select_related("created_by", "unified_document")
        .order_by("created_date")
    )

    fundraise_ct = ContentType.objects.get_for_model(Fundraise)
    sent_count = 0
    seen_pairs = set()

    for fundraise in completed_fundraises:
        pair = (fundraise.created_by_id, fundraise.unified_document_id)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)

        already_sent = Notification.objects.filter(
            notification_type=Notification.PREREGISTRATION_UPDATE_REMINDER,
            recipient=fundraise.created_by,
            content_type=fundraise_ct,
            object_id__in=Fundraise.objects.filter(
                unified_document=fundraise.unified_document,
                created_by=fundraise.created_by,
                status=Fundraise.COMPLETED,
            ).values_list("id", flat=True),
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
            log_error(
                e,
                message=f"Error sending preregistration update reminder for fundraise {fundraise.id}",
            )

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
        send_email(
            email,
            "support_receipt.txt",
            subject,
            context,
            html_template="support_receipt.html",
        )
    elif email_type == "recipient":
        subject = "Someone Sent You RSC on ResearchHub!"
        send_email(
            email,
            "support_receipt.txt",
            subject,
            context,
            html_template="support_receipt.html",
        )


def dispatch_sweep(wallet, amount, network, circle_transaction_id):
    """Schedule the sweep task after the current DB transaction commits."""
    sweep_wallet_id = wallet.get_circle_wallet_id_for_network(network)
    if sweep_wallet_id:
        transaction.on_commit(
            lambda: sweep_deposit_to_multisig.delay(
                sweep_wallet_id, amount, network, circle_transaction_id
            )
        )
    else:
        logger.error(
            "No Circle wallet ID for network=%s wallet_pk=%s "
            "circle_transaction_id=%s — skipping sweep",
            network,
            wallet.pk,
            circle_transaction_id,
        )


@app.task(
    bind=True,
    queue=QUEUE_PURCHASES,
    max_retries=3,
    default_retry_delay=60,
)
def sweep_deposit_to_multisig(self, circle_wallet_id, amount, network, sweep_reference):
    """
    Celery wrapper for CircleWalletService.execute_sweep.

    Handles retry logic; business logic lives in the service.
    """
    try:
        service = CircleWalletService()
        service.execute_sweep(
            circle_wallet_id=circle_wallet_id,
            amount=amount,
            network=network,
            sweep_reference=sweep_reference,
        )
    except Exception as exc:
        deposit = Deposit.objects.filter(circle_transaction_id=sweep_reference).first()
        if deposit and self.request.retries >= self.max_retries:
            deposit.sweep_status = Deposit.SWEEP_FAILED
            deposit.save(update_fields=["sweep_status"])
        raise self.retry(exc=exc)
