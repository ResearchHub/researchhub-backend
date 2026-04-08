from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

from research_ai.models import Expert

User = get_user_model()


@receiver(
    post_save,
    sender=User,
    dispatch_uid="research_ai_link_expert_on_user_created",
)
def on_user_created_link_expert_profile(sender, instance, created, **kwargs):
    """
    When a new user is created, link any Expert row with the same email
    via registered_user (for expert-finder / invite flows).
    """
    if not created:
        return
    email = (getattr(instance, "email", None) or "").strip()
    if not email:
        return
    Expert.objects.filter(email__iexact=email, registered_user__isnull=True).update(
        registered_user_id=instance.id
    )
