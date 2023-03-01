import json
from datetime import datetime, timedelta

import pytz
from celery.decorators import periodic_task
from celery.task.schedules import crontab
from django.contrib.contenttypes.models import ContentType
from django.db.models import DurationField, F
from django.db.models.functions import Cast

from mailing_list.lib import base_email_context
from notification.models import Notification
from reputation.lib import check_hotwallet, check_pending_withdrawal
from reputation.models import Bounty, Contribution
from researchhub.celery import QUEUE_BOUNTIES, QUEUE_CONTRIBUTIONS, QUEUE_PURCHASES, app
from researchhub.settings import PRODUCTION
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import (
    ALL,
    BOUNTY,
    FILTER_BOUNTY_EXPIRED,
    FILTER_BOUNTY_OPEN,
)
from researchhub_document.utils import reset_unified_document_cache
from user.utils import get_rh_community_user
from utils.message import send_email_message
from utils.sentry import log_info

DEFAULT_REWARD = 1000000


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


@periodic_task(
    run_every=crontab(minute="*/5"),
    priority=4,
    queue=QUEUE_PURCHASES,
)
def check_pending_withdrawals():
    check_pending_withdrawal()


@periodic_task(
    run_every=crontab(minute="*/30"),
    priority=4,
    queue=QUEUE_PURCHASES,
)
def check_hotwallet_balance():
    if PRODUCTION:
        check_hotwallet()


@periodic_task(
    run_every=crontab(hour="0, 6, 12, 18", minute=0),
    priority=4,
    queue=QUEUE_BOUNTIES,
)
def check_open_bounties():
    open_bounties = Bounty.objects.filter(status=Bounty.OPEN,).annotate(
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
            bounty_item = bounty.item
            if isinstance(bounty_item, ResearchhubUnifiedDocument):
                unified_doc = bounty_item
            else:
                unified_doc = bounty_item.unified_document
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
        hub_ids=[0],
        document_type=[ALL.lower(), BOUNTY.lower()],
        with_default_hub=True,
    )


@periodic_task(
    run_every=crontab(hour="0, 6, 12, 18", minute=0),
    priority=5,
    queue=QUEUE_BOUNTIES,
)
def send_bounty_hub_notifications():
    action_user = get_rh_community_user()
    open_bounties = Bounty.objects.filter(status=Bounty.OPEN,).annotate(
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


@periodic_task(
    run_every=crontab(hour=12, minute=0),
    priority=4,
    queue=QUEUE_BOUNTIES,
)
def recalc_hot_score_for_open_bounties():
    open_bounties = Bounty.objects.filter(status=Bounty.OPEN)

    for bounty in open_bounties:
        bounty.unified_document.calculate_hot_score_v2(should_save=True)
