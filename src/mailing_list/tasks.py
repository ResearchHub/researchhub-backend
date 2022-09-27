import logging
from datetime import timedelta

from celery.decorators import periodic_task
from celery.task.schedules import crontab
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from django.http.request import HttpRequest, QueryDict
from django.utils import timezone
from rest_framework.request import Request

from discussion.models import Comment, Reply, Thread
from hub.models import Hub
from hypothesis.models import Hypothesis
from mailing_list.lib import base_email_context
from mailing_list.models import EmailRecipient, EmailTaskLog, NotificationFrequencies
from paper.models import Paper
from researchhub.celery import QUEUE_NOTIFICATION, app
from researchhub.settings import PRODUCTION, STAGING
from researchhub_document.models import ResearchhubPost, ResearchhubUnifiedDocument
from researchhub_document.views import ResearchhubUnifiedDocumentViewSet
from user.models import Action, User
from utils.message import send_email_message


@app.task(queue=QUEUE_NOTIFICATION)
def notify_immediate(action_id):
    pass
    # actions_notifications([action_id], NotificationFrequencies.IMMEDIATE)


# Disabling digests
@periodic_task(run_every=crontab(minute="30", hour="1"), priority=7)
def notify_daily():
    return
    send_hub_digest(NotificationFrequencies.DAILY)


@periodic_task(run_every=crontab(minute="0", hour="*/3"), priority=7)
def notify_three_hours():
    return
    send_hub_digest(NotificationFrequencies.THREE_HOUR)


# Noon PST
@periodic_task(run_every=crontab(minute=0, hour=20, day_of_week="friday"), priority=9)
def notify_weekly():
    return
    send_hub_digest(NotificationFrequencies.WEEKLY)


# Noon PST
@periodic_task(run_every=crontab(minute=0, hour=20, day_of_week="friday"), priority=9)
def weekly_bounty_digest():
    send_bounty_digest(NotificationFrequencies.WEEKLY)


"""
from mailing_list.tasks import send_bounty_digest
send_bounty_digest(10080)
"""


def send_bounty_digest(frequency):
    emails = []
    etl = EmailTaskLog.objects.create(emails="", notification_frequency=frequency)

    open_bounties = ResearchhubUnifiedDocument.objects.filter(
        document_filter__bounty_open=True
    ).order_by(
        "-document_filter__bounty_total_amount",
        "document_filter__bounty_expiration_date",
    )[
        :5
    ]

    for email_recipient in EmailRecipient.objects.filter(
        bounty_digest_subscription__none=False
    ).iterator():
        recipient = email_recipient.user
        if not check_user_can_receive_bounty_digest(recipient, frequency):
            continue

        if open_bounties.count() == 0:
            continue

        paper_ids = list(open_bounties.values_list("paper__id", flat=True))
        post_ids = list(open_bounties.values_list("posts__id", flat=True))
        hypothesis_ids = list(open_bounties.values_list("hypothesis__id", flat=True))
        actions = Action.objects.filter(
            Q(
                content_type=ContentType.objects.get_for_model(Paper),
                object_id__in=paper_ids,
            )
            | Q(
                content_type=ContentType.objects.get_for_model(ResearchhubPost),
                object_id__in=post_ids,
            )
            | Q(
                content_type=ContentType.objects.get_for_model(Hypothesis),
                object_id__in=hypothesis_ids,
            )
        )

        email_context = {
            **base_email_context,
            "first_name": recipient.first_name,
            "last_name": recipient.last_name,
            "actions": [act.email_context() for act in actions],
        }

        recipient = [recipient.email]
        subject = "ResearchHub | Your Bounty Digest"
        send_email_message(
            recipient,
            "bounty_digest.txt",
            subject,
            email_context,
            "bounty_digest.html",
            "ResearchHub Bounty Digest <digest@researchhub.com>",
        )
        emails += recipient

    etl.emails = ",".join(emails)
    etl.save()


def send_editor_hub_digest(frequency):
    emails = []
    etl = EmailTaskLog.objects.create(emails="", notification_frequency=frequency)
    end_date = timezone.now()
    start_date = calculate_hub_digest_start_date(end_date, frequency)

    for hub in Hub.objects.iterator():
        editor_permissions = hub.editor_permission_groups.iterator()
        for editor_permission in editor_permissions:
            user = editor_permission.user

            if not check_editor_can_receive_digest(user, frequency):
                continue

            documents = hub.related_documents.filter(
                created_date__gte=start_date,
                created_date__lte=end_date,
                is_removed=False,
            )

            if documents.count() == 0:
                continue

            paper_ids = documents.exclude(paper__isnull=True).values_list(
                "paper_id", flat=True
            )
            post_ids = documents.exclude(posts__isnull=True).values_list(
                "posts", flat=True
            )
            hypothesis_ids = documents.exclude(hypothesis__isnull=True).values_list(
                "hypothesis", flat=True
            )

            actions = Action.objects.filter(
                Q(
                    content_type=ContentType.objects.get_for_model(Paper),
                    object_id__in=paper_ids,
                )
                | Q(
                    content_type=ContentType.objects.get_for_model(ResearchhubPost),
                    object_id__in=post_ids,
                )
                | Q(
                    content_type=ContentType.objects.get_for_model(Hypothesis),
                    object_id__in=hypothesis_ids,
                )
            ).distinct("id")

            email_context = {
                **base_email_context,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "actions": [act.email_context() for act in actions],
            }

            recipient = [user.email]
            subject = "ResearchHub | Your Editor Digest"
            send_email_message(
                recipient,
                "editor_digest.txt",
                subject,
                email_context,
                "editor_digest.html",
                "ResearchHub Digest <digest@researchhub.com>",
            )
            emails += recipient

        etl.emails = ",".join(emails)
        etl.save()


def send_hub_digest(frequency):
    etl = EmailTaskLog.objects.create(emails="", notification_frequency=frequency)
    end_date = timezone.now()
    start_date = calculate_hub_digest_start_date(end_date, frequency)

    users = Hub.objects.filter(
        subscribers__isnull=False,
        is_removed=False,
    ).values_list("subscribers", flat=True)

    # TODO find best by hub and then in mem sort for each user? more efficient?
    emails = []
    papers = []

    request_path = "/api/researchhub_unified_document/get_unified_documents/"
    if STAGING:
        http_host = "staging-backend.researchhub.com"
        protocol = "https"
    elif PRODUCTION:
        http_host = "backend.researchhub.com"
        protocol = "https"
    else:
        http_host = "localhost:8000"
        protocol = "http"

    query_string = "ordering=hot&page=1&subscribed_hubs=false&type=all&time=today&"
    http_meta = {
        "QUERY_STRING": query_string,
        "HTTP_HOST": http_host,
        "HTTP_X_FORWARDED_PROTO": protocol,
    }

    query_dict = QueryDict(query_string=query_string)
    document_view = ResearchhubUnifiedDocumentViewSet()
    http_req = HttpRequest()
    http_req.META = http_meta
    http_req.path = request_path
    req = Request(http_req)
    http_req.GET = query_dict
    document_view.request = req

    documents = document_view.get_filtered_queryset()[0:5]

    for user in User.objects.filter(id__in=users, is_suspended=False):
        if not check_can_receive_digest(user, frequency):
            continue

        recipient = [user.email]
        send_email_message(
            recipient,
            "weekly_digest_email.txt",
            "ResearchHub | Trending Papers",  # subject
            {
                # email_context
                **base_email_context,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "documents": documents,
                "preview_text": documents[0],
            },
            "weekly_digest_email.html",
            "ResearchHub Digest <digest@researchhub.com>",
        )
        emails += recipient
    etl.emails = ",".join(emails)
    etl.save()


def calculate_hub_digest_start_date(end_date, frequency):
    if frequency == NotificationFrequencies.DAILY:
        return end_date - timedelta(days=1)
    elif frequency == NotificationFrequencies.THREE_HOUR:
        return end_date - timedelta(hours=3)
    else:  # weekly
        return end_date - timedelta(days=7)


def actions_notifications(action_ids, notif_interval=NotificationFrequencies.IMMEDIATE):
    # NOTE: This only supports immediate updates for now.
    actions = Action.objects.filter(id__in=action_ids)
    user_to_action = {}
    for action in actions:
        item = action.item
        if hasattr(item, "users_to_notify"):
            for user in set(item.users_to_notify):
                try:
                    r = user.emailrecipient
                    if isinstance(item, Thread):
                        # Need to somehow differentiate
                        # between authored papers and posts
                        subscription = r.paper_subscription
                    elif isinstance(item, Comment):
                        subscription = r.comment_subscription
                    elif isinstance(item, Reply):
                        subscription = r.reply_subscription
                    else:
                        subscription = r

                    if r.receives_notifications and not subscription.none:
                        if user_to_action.get(r):
                            user_to_action[r].append(action)
                        else:
                            user_to_action[r] = [action]
                except AttributeError as e:
                    logging.warning(e)
        else:
            logging.info("action: ({action}) is missing users_to_notify field")

    for r in user_to_action:
        subject = build_subject(notif_interval)
        context = build_notification_context(user_to_action[r])
        # Remove all opted out users

        if r.emailrecipient.do_not_email or r.emailrecipient.is_opted_out:
            return

        send_email_message(
            r.email,
            "notification_email.txt",
            subject,
            context,
            html_template="notification_email.html",
        )


def build_subject(notification_frequency):
    prefix = "ResearchHub | "
    if notification_frequency == NotificationFrequencies.IMMEDIATE:
        return f"{prefix}Update"
    elif notification_frequency == NotificationFrequencies.DAILY:
        return f"{prefix}Daily Updates"
    elif notification_frequency == NotificationFrequencies.THREE_HOUR:
        return f"{prefix}Periodic Updates"
    else:
        return f"{prefix}Updates"


def build_notification_context(actions):
    context = {**base_email_context}
    if isinstance(actions, (list, tuple)):
        context["actions"] = [act.email_context() for act in actions]
    else:
        context["action"] = actions.email_context()
    return context


def check_can_receive_digest(user, frequency):
    try:
        email_recipient = user.emailrecipient
        return (
            email_recipient.receives_notifications
            and not email_recipient.digest_subscription.none
            and (
                email_recipient.digest_subscription.notification_frequency == frequency
            )  # noqa: E501
        )
    except Exception:
        return False


def check_editor_can_receive_digest(user, frequency):
    try:
        email_recipient = user.emailrecipient
        receives_notification = email_recipient.receives_notifications
        no_hub_subscription = email_recipient.hub_subscription.none
        notif_freq = (
            email_recipient.digest_subscription.notification_frequency == frequency
        )  # noqa: E501

        return receives_notification and not no_hub_subscription and notif_freq
    except Exception:
        return False


def check_user_can_receive_bounty_digest(user, frequency):
    try:
        email_recipient = user.emailrecipient
        receives_notification = email_recipient.receives_notifications
        no_bounty_subscription = email_recipient.bounty_digest_subscription.none
        notif_freq = (
            email_recipient.digest_subscription.notification_frequency == frequency
        )  # noqa: E501

        return receives_notification and not no_bounty_subscription and notif_freq
    except Exception:
        return False
