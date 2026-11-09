from django.db import models

from utils.models import DefaultModel


class GivingCampaign(DefaultModel):
    """A dated giving campaign, such as Giving Tuesday, with a public goal."""

    slug = models.SlugField(
        unique=True, db_comment="Public identifier the campaign page requests"
    )
    start_date = models.DateTimeField(
        db_comment="When gifts start counting toward the campaign"
    )
    end_date = models.DateTimeField(
        db_comment="When gifts stop counting toward the campaign"
    )
    goal_usd = models.DecimalField(
        decimal_places=2, max_digits=19, db_comment="Campaign goal in USD"
    )
    featured_grant = models.ForeignKey(
        "purchase.Grant",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="+",
        db_comment="RFP shown as the campaign's funder challenge",
    )


class GivingChallenge(DefaultModel):
    """A match or donor-count unlock that runs inside a giving campaign."""

    class Kind(models.TextChoices):
        MATCH = "MATCH", "Match"
        UNLOCK = "UNLOCK", "Unlock"

    campaign = models.ForeignKey(
        GivingCampaign, on_delete=models.CASCADE, related_name="challenges"
    )
    kind = models.CharField(
        choices=Kind.choices,
        max_length=16,
        db_comment=(
            "MATCH matches gifts to a hub's proposals 1:1 up to amount_usd; "
            "UNLOCK releases amount_usd once donor_goal donors give"
        ),
    )
    name = models.CharField(max_length=255)
    sponsor = models.CharField(
        max_length=255, db_comment="Who funds the challenge, e.g. ResearchHub"
    )
    hub = models.ForeignKey(
        "hub.Hub",
        blank=True,
        null=True,
        on_delete=models.PROTECT,
        related_name="+",
        db_comment="MATCH only: gifts to proposals in this hub are matched",
    )
    amount_usd = models.DecimalField(
        decimal_places=2,
        max_digits=19,
        db_comment="MATCH: the match cap. UNLOCK: the amount released",
    )
    donor_goal = models.PositiveIntegerField(
        blank=True,
        null=True,
        db_comment="UNLOCK only: donors needed to release amount_usd",
    )
    first_time_donors_only = models.BooleanField(
        default=False,
        db_comment="UNLOCK only: count donors whose first gift is in the window",
    )
    start_date = models.DateTimeField(
        db_comment="When gifts start counting toward the challenge"
    )
    end_date = models.DateTimeField(
        db_comment="When gifts stop counting toward the challenge"
    )

    class Meta:
        ordering = ["id"]
