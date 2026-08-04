import logging
from datetime import UTC, datetime, timedelta

from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from mailing_list.lib import base_email_context, send_transactional_email
from notification.models import Notification
from paper.models import Paper
from purchase.circle.service import CircleWalletService
from purchase.models import Balance, Fundraise, Purchase
from purchase.related_models.constants.currency import USD
from purchase.services.fundraise_service import FundraiseService
from reputation.models import Deposit
from researchhub.celery import QUEUE_NOTIFICATION, QUEUE_PURCHASES, app
from researchhub.settings import BASE_FRONTEND_URL
from researchhub_document.models import ResearchhubPost

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
    logger.info("Starting complete_eligible_fundraises task")

    # Calculate the cutoff date (7 days ago)
    cutoff_date = datetime.now(UTC) - timedelta(days=7)

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
                logger.info("Successfully completed fundraise %s", fundraise.id)

        except Exception:
            logger.exception("Error processing fundraise %s", fundraise.id)
            error_count += 1

    logger.info("Completed %d fundraises, %d errors", completed_count, error_count)
    return {
        "completed_count": completed_count,
        "error_count": error_count,
        "processed_total": completed_count + error_count,
    }


@app.task(queue=QUEUE_NOTIFICATION)
def send_monthly_preregistration_update_reminders():
    now = datetime.now(UTC)

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
        except Exception:
            logger.exception(
                "Error sending preregistration update reminder for fundraise %s",
                fundraise.id,
            )

    logger.info("Sent %d preregistration update reminders", sent_count)

    return {"sent_count": sent_count}


@app.task(queue=QUEUE_NOTIFICATION)
def send_funding_credits_reminders():
    """
    Remind users who still hold unspent funding credits to spend them.
    """
    from user.models import User

    now = datetime.now(UTC)
    reminder_cutoff = now - timedelta(days=14)
    user_ct = ContentType.objects.get_for_model(User)

    # Prefilter to users who have at least one locked, spendable balance row
    # (funding credits or promotional). The effective balance is confirmed
    # per-user below, since debits can zero it out even when credit rows exist.
    candidate_user_ids = (
        Balance.objects.filter(
            is_locked=True,
            lock_type__in=(
                Balance.LockType.FUNDING_CREDIT,
                Balance.LockType.PROMOTIONAL,
            ),
        )
        .values_list("user_id", flat=True)
        .distinct()
    )

    candidates = User.objects.filter(id__in=candidate_user_ids)

    sent_count = 0
    for user in candidates.iterator():
        balance = user.get_funding_credits_balance() + user.get_promotional_balance()
        if balance <= 0:
            continue

        already_sent = Notification.objects.filter(
            notification_type=Notification.FUNDING_CREDITS_REMINDER,
            recipient=user,
            created_date__gte=reminder_cutoff,
        ).exists()
        if already_sent:
            continue

        try:
            notification = Notification.objects.create(
                item=user,
                content_type=user_ct,
                object_id=user.id,
                action_user=user,
                recipient=user,
                notification_type=Notification.FUNDING_CREDITS_REMINDER,
                extra={"amount": str(balance)},
            )
            notification.send_notification()
            sent_count += 1
        except Exception:
            logger.exception(
                "Error sending funding credits reminder for user %s", user.id
            )

    logger.info("Sent %d funding credits reminders", sent_count)

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
    if content_type == "rhcommentmodel":
        paper = Paper.objects.get(id=paper_id)
        url = f"{BASE_FRONTEND_URL}/paper/{paper.id}/{paper.slug}#comments"
        object_supported = "thread"
    elif content_type == "researchhubpost":
        post = ResearchhubPost.objects.get(id=object_id)
        url = f"{BASE_FRONTEND_URL}/post/{post.id}/{post.slug}"
        object_supported = "post"

    if payment_type == Purchase.OFF_CHAIN:
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
        send_transactional_email(
            email,
            "support_receipt.txt",
            subject,
            context,
            html_template="support_receipt.html",
        )
    elif email_type == "recipient":
        subject = "Someone Sent You RSC on ResearchHub!"
        send_transactional_email(
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
