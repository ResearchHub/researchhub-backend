import logging
from functools import lru_cache

from allauth.socialaccount.models import SocialAccount
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from purchase.related_models.grant_model import Grant
from purchase.related_models.purchase_model import Purchase
from reputation.related_models.bounty import BountySolution
from research_ai.models import GeneratedEmail
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from user.related_models.risk_score_model import RiskScoreEvent
from user.related_models.user_model import User
from user.related_models.user_verification_model import UserVerification
from user.related_models.verdict_model import Verdict
from user.services.censorship import resolve_censorship
from user.services.risk_score_service import RiskScoreService

logger = logging.getLogger(__name__)

EventType = RiskScoreEvent.EventType

_service = RiskScoreService()


@lru_cache(maxsize=1)
def _comment_content_type_id():
    return ContentType.objects.get_for_model(RhCommentModel).id


def _run_after_commit(instance, record):
    """Defer risk-score writes until the triggering transaction commits, logging
    (never raising) failures so a scoring bug can't break the originating save."""

    def deferred():
        try:
            record()
        except Exception:
            logger.exception(
                "Risk score signal failed for %s %s",
                type(instance).__name__,
                instance.pk,
            )

    transaction.on_commit(deferred)


def _record_review_assessments_on(comment):
    if comment is None:
        return
    for review in comment.reviews.select_related("created_by"):
        if review.created_by_id:
            _service.record_event(
                review.created_by, EventType.PEER_REVIEW_ASSESSED, source=review
            )


@receiver(post_save, sender=Grant, dispatch_uid="risk_score_on_grant_status_changed")
def on_grant_status_changed(sender, instance, **kwargs):
    if instance.status == Grant.OPEN:
        event_type = EventType.WORK_APPROVED
    elif instance.status == Grant.DECLINED:
        event_type = EventType.WORK_DECLINED
    else:
        return

    def record():
        _service.record_event(instance.created_by, event_type, source=instance)

    _run_after_commit(instance, record)


@receiver(
    post_save,
    sender=ResearchhubPost,
    dispatch_uid="risk_score_on_post_status_changed",
)
def on_post_status_changed(sender, instance, **kwargs):
    """Fires WORK_APPROVED / WORK_DECLINED when a post, proposal, or journal
    entry is moderated. Requires the `status` field added in a future PR."""
    status = getattr(instance, "status", None)
    if status == "APPROVED":
        event_type = EventType.WORK_APPROVED
    elif status == "DECLINED":
        event_type = EventType.WORK_DECLINED
    else:
        return

    def record():
        _service.record_event(instance.created_by, event_type, source=instance)

    _run_after_commit(instance, record)


@receiver(
    post_save,
    sender=Verdict,
    dispatch_uid="risk_score_on_content_censored",
)
def on_content_censored(sender, instance, created, **kwargs):
    """Penalize an author only when a moderator verdict removes their content.
    Self-deletions never create a verdict, so they are never scored."""
    if not created or not instance.is_content_removed:
        return

    def record():
        author, source = resolve_censorship(instance)
        if author and source:
            _service.record_event(author, EventType.CONTENT_CENSORED, source=source)

    _run_after_commit(instance, record)


@receiver(
    post_save,
    sender=BountySolution,
    dispatch_uid="risk_score_on_bounty_solution_awarded",
)
def on_bounty_solution_awarded(sender, instance, **kwargs):
    if instance.status != BountySolution.Status.AWARDED:
        return

    def record():
        _service.record_event(
            instance.created_by, EventType.BOUNTY_AWARDED, source=instance
        )

        if instance.content_type_id != _comment_content_type_id():
            return
        if not User.is_rh_community_account(instance.bounty.created_by):
            return
        _record_review_assessments_on(instance.item)

    _run_after_commit(instance, record)


@receiver(post_save, sender=Purchase, dispatch_uid="risk_score_on_community_tip")
def on_community_tip(sender, instance, created, **kwargs):
    if not created:
        return
    if instance.content_type_id != _comment_content_type_id():
        return

    def record():
        if not User.is_rh_community_account(instance.user):
            return

        comment = instance.item
        if comment is None:
            return

        _service.record_event(
            comment.created_by, EventType.PEER_REVIEW_TIPPED, source=instance
        )
        _record_review_assessments_on(comment)

    _run_after_commit(instance, record)


@receiver(
    post_save,
    sender=SocialAccount,
    dispatch_uid="risk_score_on_social_account_created",
)
def on_social_account_created(sender, instance, created, **kwargs):
    if not created:
        return

    def record():
        if instance.provider == "google":
            _service.record_event(instance.user, EventType.GOOGLE_SIGNUP)
        elif instance.provider == "orcid" and instance.extra_data.get(
            "verified_edu_emails"
        ):
            _service.record_event(instance.user, EventType.EDU_EMAIL)

    _run_after_commit(instance, record)


@receiver(
    post_save,
    sender=UserVerification,
    dispatch_uid="risk_score_on_persona_verified",
)
def on_persona_verified(sender, instance, **kwargs):
    if instance.status != UserVerification.Status.APPROVED:
        return

    def record():
        # PERSONA_VERIFIED_NON_WHITELISTED is reserved for when UserVerification
        # gains a country field. Until then, all approved verifications use the
        # WHITELISTED variant.
        _service.record_event(instance.user, EventType.PERSONA_VERIFIED_WHITELISTED)

    _run_after_commit(instance, record)


@receiver(post_save, sender=User, dispatch_uid="risk_score_on_user_created")
def on_user_created(sender, instance, created, **kwargs):
    if not created or not instance.email:
        return

    def record():
        email = instance.email.lower()
        if email.endswith(".edu"):
            _service.record_event(instance, EventType.EDU_EMAIL)

        if GeneratedEmail.objects.filter(expert_email__iexact=email).exists():
            _service.record_event(instance, EventType.EXPERT_FINDER_SIGNUP)

    _run_after_commit(instance, record)
