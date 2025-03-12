from django.db import models

from purchase.models import Fundraise


class NonprofitOrg(models.Model):
    """
    Model representing nonprofit organizations that can be attached to preregistrations.

    These organizations are integrated with the Endaoment service for donation processing.
    """

    # Primary identifiers
    name = models.CharField(
        max_length=255, help_text="Name of the nonprofit organization"
    )
    ein = models.CharField(
        max_length=20, help_text="Employer Identification Number", null=True, blank=True
    )
    endaoment_org_id = models.CharField(
        max_length=100,
        help_text="Unique identifier for the organization in the Endaoment system",
        unique=True,
        null=True,
        blank=True,
    )

    # Financial information
    base_wallet_address = models.CharField(
        max_length=42,  # Ethereum addresses are 42 characters including '0x'
        help_text="Blockchain wallet address for the organization",
        null=True,
        blank=True,
    )

    # Standard timestamps
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

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


class NonprofitFundraiseLink(models.Model):
    """
    Join model representing the many-to-many relationship between nonprofit
    organizations and fundraising campaigns.

    This allows:
    1. A nonprofit to be associated with multiple fundraising campaigns
    2. A fundraise to support multiple nonprofits
    3. Each relationship to have a unique note
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
        help_text="Specific notes about this nonprofit for this fundraise",
        null=True,
        blank=True,
    )

    # Standard timestamps
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    def __str__(self):
        """String representation of the nonprofit-fundraise link."""
        return f"{self.nonprofit.name} - {self.fundraise.id}"

    class Meta:
        db_table = "nonprofit_fundraise_link"
        verbose_name = "Nonprofit-Fundraise Link"
        verbose_name_plural = "Nonprofit-Fundraise Links"
        unique_together = ("nonprofit", "fundraise")
        indexes = [
            models.Index(fields=["nonprofit"]),
            models.Index(fields=["fundraise"]),
        ]
