from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

from research_ai.tasks import link_experts_after_signup

User = get_user_model()


@receiver(
    post_save,
    sender=User,
    dispatch_uid="link_experts_on_user_created",
)
def on_user_created_link_experts(sender, instance, created, **kwargs):
    """
    When a new user is created, enqueue work to link ``Expert.registered_user`` when
    outreach qualifies.
    """
    if not created:
        return
    email = (getattr(instance, "email", None) or "").strip()
    if not email:
        return
    normalized = email.lower()
    link_experts_after_signup.delay(
        normalized_email=normalized,
        user_id=instance.pk,
    )
