from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Exists, OuterRef
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from research_ai.constants import EXPERT_REGISTERED_USER_LINK_WINDOW_DAYS
from research_ai.models import Expert, GeneratedEmail

User = get_user_model()


@receiver(
    post_save,
    sender=User,
    dispatch_uid="research_ai_link_expert_on_user_created",
)
def on_user_created_link_expert_profile(sender, instance, created, **kwargs):
    """
    When a new user is created, link Expert rows with the same email only if a
    non-closed GeneratedEmail for that address exists with created_date within
    EXPERT_REGISTERED_USER_LINK_WINDOW_DAYS before date_joined (inclusive).
    """
    if not created:
        return
    email = (getattr(instance, "email", None) or "").strip()
    if not email:
        return
    date_joined = getattr(instance, "date_joined", None) or timezone.now()
    window_end = date_joined
    window_start = window_end - timedelta(days=EXPERT_REGISTERED_USER_LINK_WINDOW_DAYS)

    qualifying_ge = GeneratedEmail.objects.filter(
        expert_email__iexact=OuterRef("email"),
        created_date__gte=window_start,
        created_date__lte=window_end,
    ).exclude(status=GeneratedEmail.Status.CLOSED)

    Expert.objects.filter(
        email__iexact=email,
        registered_user__isnull=True,
    ).filter(
        Exists(qualifying_ge)
    ).update(registered_user_id=instance.id)
