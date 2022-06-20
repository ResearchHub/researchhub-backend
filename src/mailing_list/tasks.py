import logging
from datetime import timedelta

from celery.decorators import periodic_task
from celery.task.schedules import crontab
from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, Q
from django.http.request import HttpRequest
from django.utils import timezone
from rest_framework.request import Request

from discussion.models import Comment, Reply, Thread
from hub.models import Hub
from hypothesis.models import Hypothesis
from mailing_list.lib import base_email_context
from mailing_list.models import EmailTaskLog, NotificationFrequencies
from paper.models import Paper
from paper.models import Vote as PaperVote
from paper.utils import get_cache_key
from researchhub.celery import QUEUE_NOTIFICATION, app
from researchhub.settings import APP_ENV, PRODUCTION, STAGING
from researchhub_document.models import ResearchhubPost
from researchhub_document.views import ResearchhubUnifiedDocumentViewSet
from user.models import Action, User
from utils.message import send_email_message


@app.task(queue=QUEUE_NOTIFICATION)
def notify_immediate(action_id):
    actions_notifications([action_id], NotificationFrequencies.IMMEDIATE)


@periodic_task(run_every=crontab(minute="30", hour="1"), priority=7)
def notify_daily():
    # send_editor_hub_digest(NotificationFrequencies.DAILY)
    send_hub_digest(NotificationFrequencies.DAILY)


@periodic_task(run_every=crontab(minute="0", hour="*/3"), priority=7)
def notify_three_hours():
    # send_editor_hub_digest(NotificationFrequencies.THREE_HOUR)
    send_hub_digest(NotificationFrequencies.THREE_HOUR)


# Noon PST
@periodic_task(run_every=crontab(minute=0, hour=20, day_of_week="friday"), priority=9)
def notify_weekly():
    # send_editor_hub_digest(NotificationFrequencies.WEEKLY)
    send_hub_digest(NotificationFrequencies.WEEKLY)


"""
from mailing_list.tasks import send_editor_hub_digest
send_editor_hub_digest(10080)
"""


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
    upvotes = Count(
        "vote",
        filter=Q(
            vote__vote_type=PaperVote.UPVOTE,
            vote__updated_date__gte=start_date,
            vote__updated_date__lte=end_date,
        ),
    )

    downvotes = Count(
        "vote",
        filter=Q(
            vote__vote_type=PaperVote.DOWNVOTE,
            vote__created_date__gte=start_date,
            vote__created_date__lte=end_date,
        ),
    )

    # TODO don't include censored threads?
    thread_counts = Count(
        "threads",
        filter=Q(
            threads__created_date__gte=start_date,
            threads__created_date__lte=end_date,
            # threads__is_removed=False,
        ),
    )

    comment_counts = Count(
        "threads__comments",
        filter=Q(
            threads__comments__created_date__gte=start_date,
            threads__comments__created_date__lte=end_date,
            # threads__comments__is_removed=False,
        ),
    )

    reply_counts = Count(
        "threads__comments__replies",
        filter=Q(
            threads__comments__replies__created_date__gte=start_date,
            threads__comments__replies__created_date__lte=end_date,
            # threads__comments__replies__is_removed=False,
        ),
    )

    users = Hub.objects.filter(
        subscribers__isnull=False,
        is_removed=False,
    ).values_list("subscribers", flat=True)

    # TODO find best by hub and then in mem sort for each user? more efficient?
    emails = []
    papers = []

    request_path = "/api/researchhub_unified_documents/get_unified_documents/"
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

    cache_key_hub = get_cache_key("hub", cache_pk)
    document_view = ResearchhubUnifiedDocumentViewSet()
    http_req = HttpRequest()
    http_req.META = http_meta
    http_req.path = request_path
    req = Request(http_req)
    document_view.request = req
    filtering = document_view._get_document_filtering({"ordering": "hot"})

    documents = document_view.get_filtered_queryset("all", filtering, "0", "today")[
        0:10
    ]

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
    return {**base_email_context, "actions": [act.email_context() for act in actions]}


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
