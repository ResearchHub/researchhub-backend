import json
import logging
from datetime import UTC, datetime, timedelta

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import DurationField, F
from django.db.models.functions import Cast

import utils.locking as lock
from hub.models import Hub
from mailing_list.services import EmailService
from notification.models import Notification
from notification.services import NotificationService
from reputation.constants.bounty import ASSESSMENT_PERIOD_DAYS
from reputation.lib import (
    broadcast_withdrawal_transfer,
    check_hotwallet,
    check_pending_withdrawal,
)
from reputation.models import Bounty, BountySolution, Contribution, Withdrawal
from reputation.related_models.paid_status_mixin import PaidStatusModelMixin
from reputation.related_models.score import Score
from reputation.services.staking_yield_service import StakingYieldService
from reputation.services.wallet import WalletService
from researchhub.celery import QUEUE_CONTRIBUTIONS, QUEUE_PURCHASES, app
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import (
    FILTER_BOUNTY_EXPIRED,
    FILTER_BOUNTY_OPEN,
)
from user.models import User
from user.related_models.author_model import Author

DEFAULT_REWARD = 1000000

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


@app.task(
    bind=True,
    queue=QUEUE_PURCHASES,
    max_retries=3,
    default_retry_delay=60,
)
def broadcast_withdrawal(self, withdrawal_id):
    """
    Broadcast an ERC-20 transfer for a committed withdrawal row.
    """
    key = lock.name(f"broadcast_withdrawal_{withdrawal_id}")
    if not lock.acquire(key):
        logger.warning("Already locked %s, skipping task", key)
        return False

    try:
        with transaction.atomic():
            withdrawal = Withdrawal.objects.select_for_update().get(id=withdrawal_id)
            broadcast_withdrawal_transfer(withdrawal)
        return True
    except Exception as exc:
        withdrawal = Withdrawal.objects.filter(id=withdrawal_id).first()
        logger.warning(
            "broadcast_withdrawal failed for %s (attempt %d/%d): %s",
            withdrawal_id,
            self.request.retries + 1,
            self.max_retries + 1,
            exc,
        )
        if self.request.retries >= self.max_retries:
            if (
                withdrawal
                and not withdrawal.transaction_hash
                and withdrawal.paid_status
                not in (
                    PaidStatusModelMixin.PAID,
                    PaidStatusModelMixin.FAILED,
                )
            ):
                withdrawal.set_paid_failed()
            logger.exception(
                "Failed to broadcast for withdrawal %s after all retries",
                withdrawal_id,
            )
            return False
        raise self.retry(exc=exc)
    finally:
        lock.release(key)
        logger.info("Released lock %s", key)


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
    now = datetime.now(UTC)
    notifications = NotificationService()
    emails = EmailService()

    open_bounties = (
        Bounty.objects.filter(status=Bounty.OPEN, parent__isnull=True)
        .select_related("created_by", "unified_document")
        .annotate(
            time_left=Cast(
                F("expiration_date") - now,
                DurationField(),
            )
        )
    )

    upcoming_expirations = open_bounties.filter(
        time_left__gt=timedelta(days=0), time_left__lte=timedelta(days=1)
    )
    for bounty in upcoming_expirations.iterator():
        bounty_creator = bounty.created_by
        notification = notifications.send_once(
            Notification.BOUNTY_EXPIRING_SOON,
            recipient=bounty_creator,
            action_user=bounty_creator,
            item=bounty,
            unified_document=bounty.unified_document,
        )
        if notification is None:
            continue

        link = bounty.unified_document.frontend_view_link()
        transaction.on_commit(
            lambda email=bounty_creator.email, link=link: emails.send_message_email(
                [email],
                "Your ResearchHub Bounty Submission Period Ending",
                (
                    "Your bounty submission period is ending in 24 hours. After "
                    "that, no new reviews will be submitted. You'll have "
                    f"{ASSESSMENT_PERIOD_DAYS} days to review and award the best "
                    "solutions."
                ),
                link=link,
                heading="Bounty Submission Period Ending Soon",
            ),
            robust=True,
        )

    # Transition OPEN -> ASSESSMENT when expiration_date passes
    expired_open_bounties = open_bounties.filter(time_left__lte=timedelta(days=0))
    for bounty in expired_open_bounties.iterator():
        bounty.assessment_end_date = now + timedelta(days=ASSESSMENT_PERIOD_DAYS)
        bounty.set_assessment_status()
        bounty.unified_document.update_filters((FILTER_BOUNTY_OPEN,))

        bounty_creator = bounty.created_by
        unified_doc = bounty.unified_document
        notifications.send(
            Notification.BOUNTY_ENTERED_ASSESSMENT,
            recipient=bounty_creator,
            action_user=bounty_creator,
            item=bounty,
            unified_document=unified_doc,
        )
        link = unified_doc.frontend_view_link()
        transaction.on_commit(
            lambda email=bounty_creator.email, link=link: emails.send_message_email(
                [email],
                "Your ResearchHub Bounty Entered Assessment Phase",
                (
                    "Submission period has ended. No new peer reviews will be "
                    f"submitted. You have {ASSESSMENT_PERIOD_DAYS} days to review and "
                    "award the best solutions."
                ),
                link=link,
                heading="Bounty Entered Assessment Phase",
            ),
            robust=True,
        )

        # Notify reviewers who submitted peer reviews on this document
        # AND solution submitters with SUBMITTED status
        # Combine both sets of user IDs, excluding bounty creator
        peer_reviews = unified_doc.get_peer_review_comments()
        peer_reviewer_ids = set(
            peer_reviews.exclude(created_by=bounty_creator)
            .values_list("created_by_id", flat=True)
            .distinct()
        )

        solution_submitter_ids = set(
            BountySolution.objects.filter(
                bounty=bounty, status=BountySolution.Status.SUBMITTED
            )
            .exclude(created_by=bounty_creator)
            .values_list("created_by_id", flat=True)
            .distinct()
        )

        all_reviewer_ids = peer_reviewer_ids | solution_submitter_ids

        for reviewer in User.objects.filter(id__in=all_reviewer_ids):
            notifications.send_once(
                Notification.BOUNTY_SOLUTION_IN_ASSESSMENT,
                recipient=reviewer,
                action_user=bounty_creator,
                item=bounty,
                unified_document=unified_doc,
            )

    # Handle ASSESSMENT bounties: transition to EXPIRED when assessment_end_date passes
    assessment_bounties = (
        Bounty.objects.filter(status=Bounty.ASSESSMENT, parent__isnull=True)
        .select_related("created_by", "unified_document")
        .annotate(
            assessment_time_left=Cast(
                F("assessment_end_date") - now,
                DurationField(),
            )
        )
    )

    # Notify creator 24 hours before assessment period ends
    upcoming_assessment_expirations = assessment_bounties.filter(
        assessment_time_left__gt=timedelta(days=0),
        assessment_time_left__lte=timedelta(days=1),
    )
    for bounty in upcoming_assessment_expirations.iterator():
        bounty_creator = bounty.created_by
        notification = notifications.send_once(
            Notification.BOUNTY_ASSESSMENT_EXPIRING_SOON,
            recipient=bounty_creator,
            action_user=bounty_creator,
            item=bounty,
            unified_document=bounty.unified_document,
        )
        if notification is None:
            continue

        link = bounty.unified_document.frontend_view_link()
        transaction.on_commit(
            lambda email=bounty_creator.email, link=link: emails.send_message_email(
                [email],
                "Your ResearchHub Bounty Assessment Period Ending",
                (
                    "Assessment period ending in 24 hours. Award solutions now or "
                    "remaining funds will be refunded."
                ),
                link=link,
                heading="Bounty Assessment Period Ending Soon",
            ),
            robust=True,
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
            logger.error("Failed to refund bounties: %s", ids)


@app.task
def recalculate_rep_all_users():
    for user in User.objects.iterator():
        try:
            user.calculate_hub_scores()
        except Exception:
            logger.exception("Error calculating rep for user %s", user.id)
            continue


@app.task
def find_qualified_users_and_notify(
    bounty_id: int, target_hubs: list[int], exclude_users: list[int]
) -> list[Notification]:
    """Find qualified users for a bounty and notify them."""
    from django.db.models import IntegerField, OuterRef, Subquery, Value
    from django.db.models.functions import Coalesce

    # Minimum reputation score required to notify a user
    min_rep_score_required_to_notify = 100

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
        .filter(max_hub_score__gte=min_rep_score_required_to_notify)
        .select_related("user")
        .order_by("-max_hub_score")
    )

    notifications = NotificationService()
    hubs = Hub.objects.in_bulk(combined_hub_ids)
    notifications_sent = []
    for author in qualified_authors:
        hub = hubs[author.matching_hub_id]
        notification = notifications.send_once(
            Notification.BOUNTY_FOR_YOU,
            recipient=author.user,
            action_user=author.user,
            item=bounty,
            unified_document=bounty.unified_document,
            extra={
                "bounty_id": bounty.id,
                "amount": bounty.amount,
                "bounty_type": bounty.bounty_type,
                "bounty_expiration_date": bounty.expiration_date,
                "user_hub_score": author.max_hub_score,
                "hub_details": json.dumps({"name": hub.name, "slug": hub.slug}),
            },
        )

        if notification:
            notifications_sent.append(notification)

    return notifications_sent


@app.task(queue=QUEUE_PURCHASES)
def burn_revenue_rsc(network="BASE"):
    """
    Weekly task to burn ResearchCoin from the revenue account.
    """
    return WalletService.burn_revenue_rsc(network)


@app.task(
    bind=True,
    queue=QUEUE_PURCHASES,
    max_retries=3,
    default_retry_delay=60,
)
def create_daily_staking_snapshots(self):
    """Daily task to create a new StakingGlobalSnapshot with fresh circulating
    supply and aggregate staking stats.

    Runs before distribute_staking_yield so the distribution task uses
    up-to-date supply and staking data.
    """
    accrual_date = datetime.now(UTC).date() - timedelta(days=1)
    key = lock.name(f"create_daily_staking_snapshots_{accrual_date}")
    if not lock.acquire(key):
        logger.warning("Already locked %s, skipping task", key)
        return False

    try:
        result = StakingYieldService.create_daily_snapshots(accrual_date)
        return result is not None
    except Exception as exc:
        logger.warning(
            "create_daily_staking_snapshots failed for %s (attempt %d/%d): %s",
            accrual_date,
            self.request.retries + 1,
            self.max_retries + 1,
            exc,
        )
        if self.request.retries >= self.max_retries:
            logger.exception(
                "create_daily_staking_snapshots failed for %s after all retries",
                accrual_date,
            )
            return False
        raise self.retry(exc=exc)
    finally:
        lock.release(key)
        logger.info("Released lock %s", key)


@app.task(
    bind=True,
    queue=QUEUE_PURCHASES,
    max_retries=3,
    default_retry_delay=60,
)
def distribute_staking_yield(self):
    """Daily task to distribute staking yield for the previous UTC day."""
    accrual_date = datetime.now(UTC).date() - timedelta(days=1)

    key = lock.name(f"distribute_staking_yield_{accrual_date}")
    if not lock.acquire(key):
        logger.warning("Already locked %s, skipping task", key)
        return False

    try:
        result = StakingYieldService.distribute_yield(accrual_date)
        return result is not None
    except Exception as exc:
        logger.warning(
            "distribute_staking_yield failed for %s (attempt %d/%d): %s",
            accrual_date,
            self.request.retries + 1,
            self.max_retries + 1,
            exc,
        )
        if self.request.retries >= self.max_retries:
            logger.exception(
                "distribute_staking_yield failed for %s after all retries",
                accrual_date,
            )
            return False
        raise self.retry(exc=exc)
    finally:
        lock.release(key)
        logger.info("Released lock %s", key)
