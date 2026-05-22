"""
Django signal handlers for the risk score system.

All real-time risk score event recording is self-contained here.
"""

from allauth.socialaccount.models import SocialAccount
from django.db.models.signals import post_save
from django.dispatch import receiver

from purchase.related_models.grant_model import Grant
from purchase.related_models.purchase_model import Purchase
from reputation.related_models.bounty import BountySolution
from research_ai.models import GeneratedEmail
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_document.models import ResearchhubUnifiedDocument
from user.related_models.risk_score_model import RiskScoreEvent
from user.related_models.user_model import User
from user.related_models.user_verification_model import UserVerification
from user.services.risk_score_service import RiskScoreService

EventType = RiskScoreEvent.EventType

_service = RiskScoreService()


# --- Grant moderation ---


@receiver(post_save, sender=Grant, dispatch_uid="risk_score_grant_moderation")
def on_grant_moderation(sender, instance, **kwargs):
    if not instance.created_by_id:
        return

    if instance.status == Grant.OPEN:
        _service.record_event(
            instance.created_by, EventType.WORK_APPROVED, source=instance
        )
    elif instance.status == Grant.DECLINED:
        _service.record_event(
            instance.created_by, EventType.WORK_DECLINED, source=instance
        )


# --- Content censored ---


@receiver(
    post_save, sender=RhCommentModel, dispatch_uid="risk_score_comment_censored"
)
def on_comment_censored(sender, instance, **kwargs):
    if not instance.is_removed:
        return
    if not instance.created_by_id:
        return
    _service.record_event(
        instance.created_by, EventType.CONTENT_CENSORED, source=instance
    )


@receiver(
    post_save,
    sender=ResearchhubUnifiedDocument,
    dispatch_uid="risk_score_document_censored",
)
def on_document_censored(sender, instance, **kwargs):
    if not instance.is_removed:
        return
    # ResearchhubUnifiedDocument.created_by is a @cached_property that
    # resolves the author via related posts/paper (the FK field is unused).
    author = instance.created_by
    if author is None:
        return
    _service.record_event(author, EventType.CONTENT_CENSORED, source=instance)


# --- Bounty solution awarded ---


@receiver(
    post_save, sender=BountySolution, dispatch_uid="risk_score_bounty_solution"
)
def on_bounty_solution_awarded(sender, instance, **kwargs):
    if instance.status != BountySolution.Status.AWARDED:
        return

    if instance.created_by_id:
        _service.record_event(
            instance.created_by, EventType.BOUNTY_AWARDED, source=instance
        )

    if instance.content_type.model != "rhcommentmodel":
        return
    if not User.is_rh_community_account(instance.bounty.created_by):
        return
    _record_assessed_reviews(instance.item)


# --- Peer review tipped / assessed ---


def _record_assessed_reviews(comment):
    """Record PEER_REVIEW_ASSESSED for all reviews attached to the comment."""
    if comment is None:
        return
    for review in comment.reviews.select_related("created_by"):
        if review.created_by_id:
            _service.record_event(
                review.created_by, EventType.PEER_REVIEW_ASSESSED, source=review
            )


@receiver(
    post_save, sender=Purchase, dispatch_uid="risk_score_community_tip"
)
def on_community_tip(sender, instance, created, **kwargs):
    if not created:
        return
    if instance.content_type.model != "rhcommentmodel":
        return
    if not User.is_rh_community_account(instance.user):
        return

    comment = instance.item
    if comment is None:
        return

    # Reward the comment author for being tipped
    if comment.created_by_id:
        _service.record_event(
            comment.created_by, EventType.PEER_REVIEW_TIPPED, source=instance
        )

    # Reward reviewers whose reviews are attached to this comment
    _record_assessed_reviews(comment)


# --- One-time profile signals ---


@receiver(
    post_save, sender=SocialAccount, dispatch_uid="risk_score_social_account"
)
def on_social_account_created(sender, instance, created, **kwargs):
    if not created:
        return

    if instance.provider == "google":
        _service.record_event(instance.user, EventType.GOOGLE_SIGNUP)
    elif instance.provider == "orcid":
        if instance.extra_data.get("verified_edu_emails"):
            _service.record_event(instance.user, EventType.ORCID_VERIFIED_EDU)


@receiver(
    post_save, sender=UserVerification, dispatch_uid="risk_score_persona_verified"
)
def on_persona_verified(sender, instance, **kwargs):
    if instance.status != UserVerification.Status.APPROVED:
        return
    # NOTE: PERSONA_VERIFIED_NON_WHITELISTED exists as an event type but
    # UserVerification has no country field. Always use WHITELISTED until
    # country data becomes available.
    _service.record_event(instance.user, EventType.PERSONA_VERIFIED_WHITELISTED)


@receiver(post_save, sender=User, dispatch_uid="risk_score_user_created")
def on_user_created(sender, instance, created, **kwargs):
    if not created:
        return
    if not instance.email:
        return

    if instance.email.lower().endswith(".edu"):
        _service.record_event(instance, EventType.EDU_EMAIL_SIGNUP)

    if GeneratedEmail.objects.filter(expert_email__iexact=instance.email).exists():
        _service.record_event(instance, EventType.EXPERT_FINDER_SIGNUP)
