from datetime import date, datetime, timedelta
from decimal import Decimal

import pytz
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from mailing_list.lib import base_email_context
from paper.models import Paper
from purchase.models import Fundraise, Purchase, StakingSnapshot, Support
from purchase.related_models.constants.currency import USD
from purchase.services.staking_service import StakingService
from referral.services.referral_bonus_service import ReferralBonusService
from researchhub.celery import QUEUE_NOTIFICATION, QUEUE_PURCHASES, app
from researchhub.settings import BASE_FRONTEND_URL
from researchhub_document.models import ResearchhubPost
from utils.message import send_email_message
from utils.sentry import log_error, log_info


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

    completed_count = 0
    error_count = 0

    for fundraise in eligible_fundraises:
        try:
            # Check if the fundraise has met its goal
            amount_raised_usd = fundraise.get_amount_raised(currency=USD)
            goal_amount_usd = float(fundraise.goal_amount)

            if amount_raised_usd >= goal_amount_usd:
                # Use atomic transaction to ensure consistency
                with transaction.atomic():
                    # Payout the funds
                    did_payout = fundraise.payout_funds()

                    if did_payout:
                        # Mark fundraise as completed
                        fundraise.status = Fundraise.COMPLETED
                        fundraise.save()

                        # Process referral bonuses for completed fundraise
                        try:
                            referral_bonus_service = ReferralBonusService()
                            referral_bonus_service.process_fundraise_completion(
                                fundraise
                            )
                        except Exception as e:
                            log_error(
                                e,
                                message=f"Failed to process referral bonuses for fundraise {fundraise.id}",
                            )

                        completed_count += 1
                        log_info(f"Successfully completed fundraise {fundraise.id}")
                    else:
                        log_error(
                            f"Failed to payout funds for fundraise {fundraise.id}"
                        )
                        error_count += 1

        except Exception as e:
            log_error(f"Error processing fundraise {fundraise.id}: {str(e)}")
            error_count += 1

    log_info(f"Completed {completed_count} fundraises, {error_count} errors")
    return {
        "completed_count": completed_count,
        "error_count": error_count,
        "processed_total": completed_count + error_count,
    }


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


@app.task(queue=QUEUE_PURCHASES)
def create_staking_snapshots():
    """
    Creates daily staking snapshots for all users with RSC balance.
    This task should run daily at 00:05 UTC.

    Snapshots capture each user's RSC balance and time-weighted multiplier
    for use in weekly reward distributions.
    """
    log_info("Starting create_staking_snapshots task")

    snapshot_date = timezone.now().date()

    # Check if snapshots already created today
    if StakingSnapshot.objects.filter(snapshot_date=snapshot_date).exists():
        log_info(f"Snapshots already created for {snapshot_date}")
        return {"status": "already_created", "date": str(snapshot_date)}

    try:
        staking_service = StakingService()
        count = staking_service.create_all_user_snapshots(snapshot_date)

        log_info(f"Created {count} staking snapshots for {snapshot_date}")
        return {
            "status": "success",
            "snapshots_created": count,
            "date": str(snapshot_date),
        }
    except Exception as e:
        log_error(e, message=f"Failed to create staking snapshots for {snapshot_date}")
        return {
            "status": "error",
            "error": str(e),
            "date": str(snapshot_date),
        }


@app.task(queue=QUEUE_PURCHASES)
def distribute_staking_rewards():
    """
    Distributes weekly staking rewards as funding credits.
    This task should run every Sunday at 12:00 PM UTC.

    Rewards are distributed proportionally based on users' weighted RSC
    holdings from the previous day's snapshot.
    """
    log_info("Starting distribute_staking_rewards task")

    distribution_date = timezone.now().date()

    try:
        staking_service = StakingService()
        record = staking_service.distribute_weekly_rewards(distribution_date)

        log_info(
            f"Distribution completed for {distribution_date}: "
            f"{record.users_rewarded} users, status={record.status}"
        )
        return {
            "status": record.status,
            "users_rewarded": record.users_rewarded,
            "total_distributed": str(record.total_pool_amount),
            "date": str(distribution_date),
        }
    except Exception as e:
        log_error(
            e, message=f"Failed to distribute staking rewards for {distribution_date}"
        )
        return {
            "status": "error",
            "error": str(e),
            "date": str(distribution_date),
        }
