import logging

from allauth.socialaccount.models import SocialAccount
from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_save
from django.dispatch import receiver

from purchase.related_models.grant_model import Grant
from purchase.related_models.purchase_model import Purchase
from reputation.related_models.bounty import BountySolution
from research_ai.models import GeneratedEmail
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from user.related_models.risk_score_model import RiskScoreEvent
from user.related_models.user_model import User
from user.related_models.user_verification_model import UserVerification
from user.services.risk_score_service import RiskScoreService

logger = logging.getLogger(__name__)

EventType = RiskScoreEvent.EventType

_service = RiskScoreService()


def _comment_content_type_id():
    return ContentType.objects.get_for_model(RhCommentModel).id


@receiver(
    post_save, sender=Grant, dispatch_uid="risk_score_on_grant_status_changed"
)
def on_grant_status_changed(sender, instance, **kwargs):
    try:
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
    except Exception:
        logger.exception(
            "Risk score signal failed for Grant %s", instance.pk
        )


@receiver(
    post_save,
    sender=ResearchhubPost,
    dispatch_uid="risk_score_on_post_status_changed",
)
def on_post_status_changed(sender, instance, **kwargs):
    """Fires WORK_APPROVED / WORK_DECLINED when a post, proposal, or journal
    entry is moderated. Requires the `status` field added in a future PR."""
    try:
        status = getattr(instance, "status", None)
        if status is None:
            return
        if not instance.created_by_id:
            return

        if status == "APPROVED":
            _service.record_event(
                instance.created_by, EventType.WORK_APPROVED, source=instance
            )
        elif status == "DECLINED":
            _service.record_event(
                instance.created_by, EventType.WORK_DECLINED, source=instance
            )
    except Exception:
        logger.exception(
            "Risk score signal failed for ResearchhubPost %s", instance.pk
        )


@receiver(
    post_save,
    sender=RhCommentModel,
    dispatch_uid="risk_score_on_comment_censored",
)
def on_comment_censored(sender, instance, **kwargs):
    try:
        if not instance.is_removed or not instance.created_by_id:
            return
        _service.record_event(
            instance.created_by, EventType.CONTENT_CENSORED, source=instance
        )
    except Exception:
        logger.exception(
            "Risk score signal failed for RhCommentModel %s", instance.pk
        )


@receiver(
    post_save,
    sender=ResearchhubUnifiedDocument,
    dispatch_uid="risk_score_on_document_censored",
)
def on_document_censored(sender, instance, **kwargs):
    try:
        if not instance.is_removed:
            return
        author = instance.created_by
        if author is None:
            return
        _service.record_event(
            author, EventType.CONTENT_CENSORED, source=instance
        )
    except Exception:
        logger.exception(
            "Risk score signal failed for ResearchhubUnifiedDocument %s",
            instance.pk,
        )


@receiver(
    post_save,
    sender=BountySolution,
    dispatch_uid="risk_score_on_bounty_solution_awarded",
)
def on_bounty_solution_awarded(sender, instance, **kwargs):
    try:
        if instance.status != BountySolution.Status.AWARDED:
            return

        if instance.created_by_id:
            _service.record_event(
                instance.created_by, EventType.BOUNTY_AWARDED, source=instance
            )

        if instance.content_type_id != _comment_content_type_id():
            return
        if not User.is_rh_community_account(instance.bounty.created_by):
            return
        _record_review_assessments_on(instance.item)
    except Exception:
        logger.exception(
            "Risk score signal failed for BountySolution %s", instance.pk
        )


def _record_review_assessments_on(comment):
    if comment is None:
        return
    for review in comment.reviews.select_related("created_by"):
        if review.created_by_id:
            _service.record_event(
                review.created_by, EventType.PEER_REVIEW_ASSESSED, source=review
            )


@receiver(
    post_save, sender=Purchase, dispatch_uid="risk_score_on_community_tip"
)
def on_community_tip(sender, instance, created, **kwargs):
    try:
        if not created:
            return
        if instance.content_type_id != _comment_content_type_id():
            return
        if not User.is_rh_community_account(instance.user):
            return

        comment = instance.item
        if comment is None:
            return

        if comment.created_by_id:
            _service.record_event(
                comment.created_by, EventType.PEER_REVIEW_TIPPED, source=instance
            )
        _record_review_assessments_on(comment)
    except Exception:
        logger.exception(
            "Risk score signal failed for Purchase %s", instance.pk
        )


@receiver(
    post_save,
    sender=SocialAccount,
    dispatch_uid="risk_score_on_social_account_created",
)
def on_social_account_created(sender, instance, created, **kwargs):
    try:
        if not created:
            return

        if instance.provider == "google":
            _service.record_event(instance.user, EventType.GOOGLE_SIGNUP)
        elif instance.provider == "orcid" and instance.extra_data.get(
            "verified_edu_emails"
        ):
            _service.record_event(instance.user, EventType.ORCID_VERIFIED_EDU)
    except Exception:
        logger.exception(
            "Risk score signal failed for SocialAccount %s", instance.pk
        )


@receiver(
    post_save,
    sender=UserVerification,
    dispatch_uid="risk_score_on_persona_verified",
)
def on_persona_verified(sender, instance, **kwargs):
    try:
        if instance.status != UserVerification.Status.APPROVED:
            return
        # PERSONA_VERIFIED_NON_WHITELISTED is reserved for when UserVerification
        # gains a country field. Until then, all approved verifications use
        # the WHITELISTED variant.
        _service.record_event(
            instance.user, EventType.PERSONA_VERIFIED_WHITELISTED
        )
    except Exception:
        logger.exception(
            "Risk score signal failed for UserVerification %s", instance.pk
        )


@receiver(post_save, sender=User, dispatch_uid="risk_score_on_user_created")
def on_user_created(sender, instance, created, **kwargs):
    try:
        if not created or not instance.email:
            return

        email = instance.email.lower()
        if email.endswith(".edu"):
            _service.record_event(instance, EventType.EDU_EMAIL_SIGNUP)

        if GeneratedEmail.objects.filter(expert_email__iexact=email).exists():
            _service.record_event(instance, EventType.EXPERT_FINDER_SIGNUP)
    except Exception:
        logger.exception(
            "Risk score signal failed for User %s", instance.pk
        )
