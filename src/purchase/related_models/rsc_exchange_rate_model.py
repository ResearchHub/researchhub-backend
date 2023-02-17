from django.db import models

from purchase.related_models.constants.rsc_exchange_currency import (
    MORALIS,
    PRICE_SOURCES,
    RSC_EXCHANGE_CURRENCY,
)
from utils.models import DefaultModel


class RscExchangeRate(DefaultModel):
    price_source = models.CharField(
        blank=False,
        choices=PRICE_SOURCES,
        default=MORALIS,
        help_text="API used to get the price",
        max_length=255,
        null=True,
    )
    rate = models.FloatField(
        blank=False,
        help_text="""
            RSC to target currency rate.
            For example, rate of 3 to USD represents 3 dollars per RSC.
            This is may not reflect the market fully for internal purposes.
            We may adjust the rate for different purposes.
        """,
        null=False,
    )
    real_rate = models.FloatField(
        blank=True,
        help_text="""
            RSC exchange rate. This may differ from 'rate' field if real rate is lower
            than the floor-rate (arbitrary) of the recorded date.
        """,
        null=True,
    )
    target_currency = models.CharField(
        blank=False,
        choices=RSC_EXCHANGE_CURRENCY,
        db_index=True,
        max_length=255,
        null=False,
    )
