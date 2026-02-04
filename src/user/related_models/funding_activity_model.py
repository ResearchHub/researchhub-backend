from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from utils.models import DefaultModel


class FundingActivity(DefaultModel):
    """
    Tracks all funding-related activities on the platform including:
    - Fundraise payouts (when a fundraise completes)
    - Bounty payouts (reviewer earnings from bounties)
    - Document tips (BOOST purchases on papers/posts)
    - Review tips (tips given to reviewers)
    - Platform fees (DAO fees, RH fees, support fees)
    """

    # Source type choices
    FUNDRAISE_PAYOUT = "FUNDRAISE_PAYOUT"
    BOUNTY_PAYOUT = "BOUNTY_PAYOUT"
    TIP_DOCUMENT = "TIP_DOCUMENT"
    TIP_REVIEW = "TIP_REVIEW"
    FEE = "FEE"

    SOURCE_TYPE_CHOICES = [
        (FUNDRAISE_PAYOUT, "Fundraise Payout"),
        (BOUNTY_PAYOUT, "Bounty Payout"),
        (TIP_DOCUMENT, "Document Tip"),
        (TIP_REVIEW, "Review Tip"),
        (FEE, "Platform Fee"),
    ]

    funder = models.ForeignKey(
        "user.User",
        on_delete=models.CASCADE,
        related_name="funding_activities",
        help_text="The user who provided the funding",
    )
    source_type = models.CharField(
        max_length=32,
        choices=SOURCE_TYPE_CHOICES,
        help_text="Type of funding activity",
    )
    total_amount = models.DecimalField(
        max_digits=19,
        decimal_places=8,
        help_text="Total RSC amount for this activity",
    )
    unified_document = models.ForeignKey(
        "researchhub_document.ResearchhubUnifiedDocument",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="funding_activities",
    )
    activity_date = models.DateTimeField(
        db_index=True,
        help_text="When the funding activity occurred",
    )

    # Generic foreign key to the source object (Purchase, Distribution, EscrowRecipients)
    source_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
    )
    source_object_id = models.PositiveIntegerField()
    source = GenericForeignKey("source_content_type", "source_object_id")

    class Meta:
        verbose_name = "Funding Activity"
        verbose_name_plural = "Funding Activities"
        ordering = ["-activity_date"]
        indexes = [
            models.Index(
                fields=["funder", "activity_date"],
                name="funding_funder_date_idx",
            ),
            models.Index(
                fields=["source_type", "activity_date"],
                name="funding_type_date_idx",
            ),
            models.Index(
                fields=["unified_document", "activity_date"],
                name="funding_doc_date_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["source_content_type", "source_object_id"],
                name="unique_funding_source",
            ),
        ]

    def __str__(self):
        return (
            f"FundingActivity: {self.source_type} - "
            f"{self.total_amount} RSC by User {self.funder_id}"
        )


class FundingActivityRecipient(DefaultModel):
    """
    Tracks individual recipients of a funding activity.
    A single FundingActivity can have multiple recipients
    (e.g., bounty split between reviewers).
    """

    activity = models.ForeignKey(
        FundingActivity,
        on_delete=models.CASCADE,
        related_name="recipients",
        help_text="The funding activity this recipient belongs to",
    )
    recipient_user = models.ForeignKey(
        "user.User",
        on_delete=models.CASCADE,
        related_name="funding_received",
        help_text="The user who received the funding",
    )
    amount = models.DecimalField(
        max_digits=19,
        decimal_places=8,
        help_text="RSC amount received by this recipient",
    )

    class Meta:
        verbose_name = "Funding Activity Recipient"
        verbose_name_plural = "Funding Activity Recipients"
        indexes = [
            models.Index(
                fields=["recipient_user"],
                name="funding_recipient_user_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["activity", "recipient_user"],
                name="unique_activity_recipient",
            ),
        ]

    def __str__(self):
        return (
            f"FundingRecipient: User {self.recipient_user_id} "
            f"received {self.amount} RSC"
        )
