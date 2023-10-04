from django.db import models

from utils.models import DefaultModel


class PredictionMarketVote(DefaultModel):
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

    vote = models.BooleanField(
        blank=False,
        null=False,
    )

    bet_amount = models.DecimalField(
        max_digits=19,
        decimal_places=10,
        blank=True,
        null=True,
    )
