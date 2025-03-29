from django.db import models

from purchase.models import Fundraise
from utils.models import DefaultModel


class NonprofitOrg(DefaultModel):
    """
    Model representing nonprofit organizations that can be attached to
    preregistrations.

    These organizations are integrated with the Endaoment service for donation
    processing.
    """

    # Primary identifiers
    name = models.TextField(help_text="Name of the nonprofit organization")
    ein = models.CharField(
        max_length=10,
        help_text="Employer Identification Number (9 digits, may include hyphen)",
        blank=True,
        default="",
    )
    endaoment_org_id = models.TextField(
        help_text="Unique ID in the Endaoment system",
        blank=True,
        default="",
    )

    # Financial information
    base_wallet_address = models.CharField(
        max_length=42,  # Ethereum addresses are 42 characters including '0x'
        help_text="Blockchain wallet address for the organization",
        blank=True,
        default="",
    )

    def __str__(self):
        """String representation of the nonprofit organization."""
        return f"{self.name} ({self.ein or 'No EIN'})"

    class Meta:
        db_table = "nonprofit_org"
        verbose_name = "Nonprofit Organization"
        verbose_name_plural = "Nonprofit Organizations"
        indexes = [
            models.Index(fields=["endaoment_org_id"]),
            models.Index(fields=["ein"]),
        ]


class NonprofitFundraiseLink(DefaultModel):
    """
    Join model representing the many-to-many relationship between nonprofit
    organizations and fundraising campaigns.

    Each fundraise can only be associated with one nonprofit at a time.
    The note field allows for additional context about the relationship.
    """

    nonprofit = models.ForeignKey(
        NonprofitOrg,
        on_delete=models.CASCADE,
        related_name="fundraise_links",
        help_text="The nonprofit organization",
    )

    fundraise = models.ForeignKey(
        Fundraise,
        on_delete=models.CASCADE,
        related_name="nonprofit_links",
        help_text="The fundraising campaign",
    )

    note = models.TextField(
        help_text="Notes about this nonprofit for this fundraise",
        blank=True,
        default="",
    )

    def __str__(self):
        """String representation of the nonprofit-fundraise link."""
        return f"{self.nonprofit.name} - {self.fundraise.id}"

    class Meta:
        db_table = "nonprofit_fundraise_link"
        verbose_name = "Nonprofit-Fundraise Link"
        verbose_name_plural = "Nonprofit-Fundraise Links"
        constraints = [
            models.UniqueConstraint(fields=["fundraise"], name="unique_fundraise")
        ]
        indexes = [
            models.Index(fields=["nonprofit"]),
            models.Index(fields=["fundraise"]),
        ]
