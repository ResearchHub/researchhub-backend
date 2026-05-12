from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils.translation import gettext_lazy as _

from risk_score.constants import DEFAULT_SCORE
from utils.models import DefaultModel


class RiskScore(DefaultModel):
    user = models.OneToOneField(
        "user.User",
        on_delete=models.CASCADE,
        related_name="risk_score",
    )
    score = models.IntegerField(default=DEFAULT_SCORE, db_index=True)

    def __str__(self):
        return f"User {self.user_id} - Score: {self.score}"


class RiskScoreEvent(models.Model):
    class EventType(models.TextChoices):
        # Content moderation (positive)
        GRANT_APPROVED = "GRANT_APPROVED", _("Grant approved")
        POST_APPROVED = "POST_APPROVED", _("Post approved")
        JOURNAL_ENTRY_APPROVED = "JOURNAL_ENTRY_APPROVED", _("Journal entry approved")
        PROPOSAL_APPROVED = "PROPOSAL_APPROVED", _("Proposal approved")

        # Content moderation (negative)
        GRANT_DECLINED = "GRANT_DECLINED", _("Grant declined")
        POST_DECLINED = "POST_DECLINED", _("Post declined")
        JOURNAL_ENTRY_DECLINED = "JOURNAL_ENTRY_DECLINED", _("Journal entry declined")
        PROPOSAL_DECLINED = "PROPOSAL_DECLINED", _("Proposal declined")

        # Community signals
        COMMENT_UPVOTED = "COMMENT_UPVOTED", _("Comment upvoted")
        POST_UPVOTED = "POST_UPVOTED", _("Post upvoted")
        COMMENT_DOWNVOTED = "COMMENT_DOWNVOTED", _("Comment downvoted")

        # Content removal
        COMMENT_CENSORED = "COMMENT_CENSORED", _("Comment censored")
        POST_CENSORED = "POST_CENSORED", _("Post censored")
        PAPER_CENSORED = "PAPER_CENSORED", _("Paper censored")

        # Bounties
        BOUNTY_AWARDED_FOUNDATION = "BOUNTY_AWARDED_FOUNDATION", _("Bounty awarded (foundation)")
        BOUNTY_AWARDED_COMMUNITY = "BOUNTY_AWARDED_COMMUNITY", _("Bounty awarded (community)")

        # Expert activity
        PEER_REVIEW_ASSESSED = "PEER_REVIEW_ASSESSED", _("Peer review assessed")
        PAPER_SURVIVED_30_DAYS = "PAPER_SURVIVED_30_DAYS", _("Paper survived 30 days")

        # Flags / moderation
        FLAG_UPHELD = "FLAG_UPHELD", _("Flag upheld")
        MARKED_PROBABLE_SPAMMER = "MARKED_PROBABLE_SPAMMER", _("Marked probable spammer")

        # One-time profile signals
        EXPERT_FINDER_SIGNUP = "EXPERT_FINDER_SIGNUP", _("Expert Finder signup")
        ORCID_CONNECTED = "ORCID_CONNECTED", _("ORCID connected")
        IDENTITY_VERIFIED = "IDENTITY_VERIFIED", _("Identity verified")
        EMAIL_VERIFIED = "EMAIL_VERIFIED", _("Email verified")
        ACCOUNT_AGE_BONUS = "ACCOUNT_AGE_BONUS", _("Account age bonus")

        # System
        ACCOUNT_CREATED = "ACCOUNT_CREATED", _("Account created")
        MANUAL_ADJUSTMENT = "MANUAL_ADJUSTMENT", _("Manual adjustment")
        BACKFILL = "BACKFILL", _("Backfill")

    DELTAS = {
        EventType.GRANT_APPROVED: -15,
        EventType.POST_APPROVED: -5,
        EventType.JOURNAL_ENTRY_APPROVED: -5,
        EventType.PROPOSAL_APPROVED: -10,
        EventType.GRANT_DECLINED: 20,
        EventType.POST_DECLINED: 10,
        EventType.JOURNAL_ENTRY_DECLINED: 10,
        EventType.PROPOSAL_DECLINED: 15,
        EventType.COMMENT_UPVOTED: -1,
        EventType.POST_UPVOTED: -1,
        EventType.COMMENT_DOWNVOTED: 1,
        EventType.COMMENT_CENSORED: 10,
        EventType.POST_CENSORED: 15,
        EventType.PAPER_CENSORED: 15,
        EventType.BOUNTY_AWARDED_FOUNDATION: -10,
        EventType.BOUNTY_AWARDED_COMMUNITY: -5,
        EventType.PEER_REVIEW_ASSESSED: -5,
        EventType.PAPER_SURVIVED_30_DAYS: -3,
        EventType.FLAG_UPHELD: 10,
        EventType.MARKED_PROBABLE_SPAMMER: 50,
        EventType.EXPERT_FINDER_SIGNUP: -20,
        EventType.ORCID_CONNECTED: -10,
        EventType.IDENTITY_VERIFIED: -15,
        EventType.EMAIL_VERIFIED: -5,
        EventType.ACCOUNT_AGE_BONUS: -5,
        EventType.ACCOUNT_CREATED: 0,
        EventType.MANUAL_ADJUSTMENT: 0,
        EventType.BACKFILL: 0,
    }

    VOTE_TYPES = {
        EventType.COMMENT_UPVOTED,
        EventType.POST_UPVOTED,
        EventType.COMMENT_DOWNVOTED,
    }

    ONE_TIME_TYPES = {
        EventType.EXPERT_FINDER_SIGNUP,
        EventType.ORCID_CONNECTED,
        EventType.IDENTITY_VERIFIED,
        EventType.EMAIL_VERIFIED,
        EventType.ACCOUNT_AGE_BONUS,
    }

    user = models.ForeignKey(
        "user.User",
        on_delete=models.CASCADE,
        related_name="risk_score_events",
    )
    event_type = models.CharField(max_length=64, choices=EventType.choices)
    delta = models.IntegerField()
    score_after = models.IntegerField()
    metadata = models.JSONField(default=dict, blank=True)

    related_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    related_object_id = models.PositiveIntegerField(null=True, blank=True)
    related_object = GenericForeignKey("related_content_type", "related_object_id")

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
