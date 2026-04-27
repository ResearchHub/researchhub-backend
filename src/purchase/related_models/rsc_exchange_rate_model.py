from datetime import timedelta
from typing import override

from django.core.cache import cache
from django.db import models
from django.db.models import Avg
from django.utils import timezone

from purchase.related_models.constants.currency import USD
from purchase.related_models.constants.rsc_exchange_currency import (
    MORALIS,
    PRICE_SOURCES,
    RSC_EXCHANGE_CURRENCY,
)
from utils.models import DefaultModel


class RscExchangeRate(DefaultModel):

    _CACHE_TIMEOUT: int = 60 * 75  # 75 minutes
    _LATEST_EXCHANGE_RATE_CACHE_KEY: str = "latest_exchange_rate"

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

    @override
    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        cache.delete(self._LATEST_EXCHANGE_RATE_CACHE_KEY)

    @classmethod
    def get_average_rate(cls, days: int = 3, target_currency: str = USD) -> float:
        cutoff = timezone.now() - timedelta(days=days)
        avg = cls.objects.filter(
            target_currency=target_currency,
            created_date__gte=cutoff,
        ).aggregate(avg=Avg("rate"))["avg"]
        if avg is None:
            return cls.get_latest()
        return avg

    @classmethod
    def get_latest(cls, force_refresh: bool = False) -> float:
        if not force_refresh:
            cached_rate = cache.get(cls._LATEST_EXCHANGE_RATE_CACHE_KEY)
            if cached_rate is not None:
                return cached_rate
        rate = cls.objects.last().rate
        cache.set(
            cls._LATEST_EXCHANGE_RATE_CACHE_KEY,
            rate,
            timeout=cls._CACHE_TIMEOUT,
        )
        return rate

    @staticmethod
    def eth_to_rsc(eth_amount):
        from user.rsc_exchange_rate_record_tasks import get_rsc_eth_conversion

        eth_to_rsc_conversion = get_rsc_eth_conversion().get("rate")
        return eth_amount / eth_to_rsc_conversion

    @classmethod
    def usd_to_rsc(cls, usd_amount, force_refresh=False):
        latest_exchange_rate = cls.get_latest(force_refresh=force_refresh)
        return usd_amount / latest_exchange_rate

    @classmethod
    def rsc_to_usd(cls, rsc_amount, force_refresh=False):
        latest_exchange_rate = cls.get_latest(force_refresh=force_refresh)
        return rsc_amount * latest_exchange_rate

    @staticmethod
    def rsc_to_eth(rsc_amount):
        from user.rsc_exchange_rate_record_tasks import get_rsc_eth_conversion

        eth_to_rsc_conversion = get_rsc_eth_conversion().get("rate")
        return rsc_amount * eth_to_rsc_conversion
