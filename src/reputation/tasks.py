from datetime import datetime, timedelta

import pytz
from celery.decorators import periodic_task
from celery.task.schedules import crontab
from django.contrib.contenttypes.models import ContentType
from django.db.models import DurationField, F
from django.db.models.functions import Cast

from notification.models import Notification
from reputation.models import Bounty, Contribution
from researchhub.celery import QUEUE_BOUNTIES, QUEUE_CONTRIBUTIONS, app
from researchhub_document.models import ResearchhubUnifiedDocument
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
    run_every=crontab(hour="0, 6, 12, 18"),
    priority=4,
    queue=QUEUE_BOUNTIES,
)
def check_open_bounties():
    from mailing_list.tasks import build_notification_context

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
        bounty_action = bounty.actions.first()
        # Sends a notification if no notification exists for current bounty
        if not Notification.objects.filter(action=bounty_action).exists():
            bounty_creator = bounty.created_by
            notification = Notification.objects.create(
                action=bounty_action,
                action_user=bounty_creator,
                recipient=bounty_creator,
            )
            notification.send_notification()

            outer_subject = "Your ResearchHub Bounty is Expiring"
            context = build_notification_context(bounty_action)
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
        bounty.set_expired_status()
        refund_status = bounty.refund()
        if refund_status is False:
            ids = expired_bounties.values_list("id", flat=True)
            log_info(f"Failed to refund bounties: {ids}")
