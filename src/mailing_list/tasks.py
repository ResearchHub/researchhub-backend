from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from django.utils import timezone

from hub.models import Hub
from mailing_list.lib import base_email_context
from mailing_list.models import EmailTaskLog
from paper.models import Paper
from researchhub.settings import EMAIL_DOMAIN
from researchhub_document.models import ResearchhubPost
from user.models import Action
from utils.message import send_email_message


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
