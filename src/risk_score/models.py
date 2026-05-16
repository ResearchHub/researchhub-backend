from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from risk_score.constants import DEFAULT_SCORE
from utils.models import DefaultModel


class RiskScore(DefaultModel):
    user = models.OneToOneField(
        "user.User",
        on_delete=models.CASCADE,
        related_name="risk_score",
    )
    score = models.IntegerField(default=DEFAULT_SCORE)

    class Meta:
        indexes = [
            models.Index(fields=["score"], name="risk_score_score_idx"),
        ]

    def __str__(self):
        return f"User {self.user_id} - Score: {self.score}"


class RiskScoreEvent(models.Model):
    class EventType(models.TextChoices):
        # Content moderation
        WORK_APPROVED = "WORK_APPROVED", "Work approved"
        WORK_DECLINED = "WORK_DECLINED", "Work declined"
        CONTENT_CENSORED = "CONTENT_CENSORED", "Content censored"

        # Bounties and tips
        BOUNTY_AWARDED = "BOUNTY_AWARDED", "Bounty awarded"
        PEER_REVIEW_TIPPED = "PEER_REVIEW_TIPPED", "Peer review tipped"
        PEER_REVIEW_ASSESSED = "PEER_REVIEW_ASSESSED", "Peer review assessed"

        # One-time profile signals
        EXPERT_FINDER_SIGNUP = "EXPERT_FINDER_SIGNUP", "Expert Finder signup"
        EDU_EMAIL_SIGNUP = "EDU_EMAIL_SIGNUP", "Signed up with edu email"
        ORCID_VERIFIED_EDU = "ORCID_VERIFIED_EDU", "ORCID verified edu email"
        GOOGLE_SIGNUP = "GOOGLE_SIGNUP", "Signed up via Google"
        ACCOUNT_AGE_BONUS = "ACCOUNT_AGE_BONUS", "Account age bonus"
        PERSONA_VERIFIED_WHITELISTED = (
            "PERSONA_VERIFIED_WHITELISTED",
            "Persona verified (whitelisted country)",
        )
        PERSONA_VERIFIED_NON_WHITELISTED = (
            "PERSONA_VERIFIED_NON_WHITELISTED",
            "Persona verified (non-whitelisted country)",
        )

    DELTAS = {
        # Content moderation
        EventType.WORK_APPROVED: -50,
        EventType.WORK_DECLINED: 20,
        EventType.CONTENT_CENSORED: 15,
        # Bounties and tips
        EventType.BOUNTY_AWARDED: -10,
        EventType.PEER_REVIEW_TIPPED: -5,
        EventType.PEER_REVIEW_ASSESSED: -5,
        # One-time profile signals
        EventType.EXPERT_FINDER_SIGNUP: -51,
        EventType.EDU_EMAIL_SIGNUP: -20,
        EventType.ORCID_VERIFIED_EDU: -10,
        EventType.GOOGLE_SIGNUP: -10,
        EventType.ACCOUNT_AGE_BONUS: -5,
        EventType.PERSONA_VERIFIED_WHITELISTED: -51,
        EventType.PERSONA_VERIFIED_NON_WHITELISTED: -10,
    }

    # Events that can only be recorded once per user. The service layer
    # enforces idempotency by checking for existing events before recording.
    ONE_TIME_TYPES = {
        EventType.EXPERT_FINDER_SIGNUP,
        EventType.EDU_EMAIL_SIGNUP,
        EventType.ORCID_VERIFIED_EDU,
        EventType.GOOGLE_SIGNUP,
        EventType.ACCOUNT_AGE_BONUS,
        EventType.PERSONA_VERIFIED_WHITELISTED,
        EventType.PERSONA_VERIFIED_NON_WHITELISTED,
    }

    user = models.ForeignKey(
        "user.User",
        on_delete=models.CASCADE,
        related_name="risk_score_events",
    )
    event_type = models.CharField(max_length=64)
    delta = models.IntegerField()

    source_content_id = models.PositiveIntegerField(null=True, blank=True)
    source_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    source = GenericForeignKey("source_content_type", "source_content_id")

    created_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_date"]
        indexes = [
            models.Index(
                fields=["user", "event_type"],
                name="risk_event_user_type_idx",
            ),
            models.Index(
                fields=["user", "created_date"],
                name="risk_event_user_date_idx",
            ),
        ]

    def __str__(self):
        return f"User {self.user_id} - {self.event_type} ({self.delta:+d})"
