import logging

from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from django.utils import timezone

from hub.models import Hub
from mailing_list.lib import base_email_context
from mailing_list.models import EmailRecipient, EmailTaskLog, NotificationFrequencies
from paper.models import Paper
from researchhub.celery import app
from researchhub.settings import EMAIL_DOMAIN
from researchhub_document.models import ResearchhubPost, ResearchhubUnifiedDocument
from user.models import Action
from utils.message import send_email_message


@app.task
def weekly_bounty_digest():
    send_bounty_digest(NotificationFrequencies.WEEKLY)


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
    if open_bounties.count() == 0:
        return

    for email_recipient in EmailRecipient.objects.filter(
        bounty_digest_subscription__none=False
    ).iterator():
        recipient = email_recipient.user
        if not check_user_can_receive_bounty_digest(recipient, frequency):
            continue

        paper_ids = list(open_bounties.values_list("paper__id", flat=True))
        post_ids = list(open_bounties.values_list("posts__id", flat=True))
        actions = Action.objects.filter(
            Q(
                content_type=ContentType.objects.get_for_model(Paper),
                object_id__in=paper_ids,
            )
            | Q(
                content_type=ContentType.objects.get_for_model(ResearchhubPost),
                object_id__in=post_ids,
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
            f"ResearchHub Bounty Digest <digest@{EMAIL_DOMAIN}>",
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

            actions = Action.objects.filter(
                Q(
                    content_type=ContentType.objects.get_for_model(Paper),
                    object_id__in=paper_ids,
                )
                | Q(
                    content_type=ContentType.objects.get_for_model(ResearchhubPost),
                    object_id__in=post_ids,
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
                f"ResearchHub Digest <digest@{EMAIL_DOMAIN}>",
            )
            emails += recipient

        etl.emails = ",".join(emails)
        etl.save()


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
