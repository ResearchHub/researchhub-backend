from django.db import models

from django.core.cache import cache
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

    @staticmethod
    def get_latest_exchange_rate(
        force_refresh=False,
    ):
        rate = cache.get('latest_exchange_rate')
        if rate is None or force_refresh:
            rate = RscExchangeRate.objects.last().rate
            cache.set('latest_exchange_rate', rate, timeout=60 * 5) # 5 minutes
        return rate

    @staticmethod
    def eth_to_rsc(eth_amount):
        from user.rsc_exchange_rate_record_tasks import get_rsc_eth_conversion

        eth_to_rsc_conversion = get_rsc_eth_conversion().get("rate")
        return eth_amount / eth_to_rsc_conversion

    @staticmethod
    def usd_to_rsc(usd_amount, force_refresh=False):
        latest_exchange_rate = RscExchangeRate.get_latest_exchange_rate(force_refresh=force_refresh)
        return usd_amount / latest_exchange_rate

    @staticmethod
    def rsc_to_usd(rsc_amount, force_refresh=False):
        latest_exchange_rate = RscExchangeRate.get_latest_exchange_rate(force_refresh=force_refresh)
        return rsc_amount * latest_exchange_rate

    @staticmethod
    def rsc_to_eth(rsc_amount):
        from user.rsc_exchange_rate_record_tasks import get_rsc_eth_conversion

        eth_to_rsc_conversion = get_rsc_eth_conversion().get("rate")
        return rsc_amount * eth_to_rsc_conversion
