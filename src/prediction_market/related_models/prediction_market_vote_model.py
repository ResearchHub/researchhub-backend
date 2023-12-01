from django.db import models

from utils.models import DefaultModel


class PredictionMarketVote(DefaultModel):
    VOTE_YES = "YES"
    VOTE_NO = "NO"
    VOTE_NEUTRAL = "NEUTRAL"
    VOTE_CHOICES = [
        (VOTE_YES, VOTE_YES),
        (VOTE_NO, VOTE_NO),
        (VOTE_NEUTRAL, VOTE_NEUTRAL),
    ]

    created_by = models.ForeignKey(
        "user.User",
        related_name="prediction_market_votes",
        blank=False,
        null=False,
        on_delete=models.CASCADE,
    )

    prediction_market = models.ForeignKey(
        "prediction_market.PredictionMarket",
        related_name="prediction_market_votes",
        blank=False,
        null=False,
        on_delete=models.CASCADE,
    )

    vote = models.CharField(
        choices=VOTE_CHOICES,
        default=VOTE_NEUTRAL,
        max_length=32,
        blank=False,
        null=False,
    )

    bet_amount = models.DecimalField(
        max_digits=19,
        decimal_places=10,
        blank=True,
        null=True,
    )
