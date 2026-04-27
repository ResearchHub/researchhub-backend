from datetime import timedelta

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from purchase.models import RscExchangeRate
from purchase.related_models.constants.currency import ETHER, USD


class GetAverageRateTests(TestCase):
    def setUp(self):
        cache.clear()

    def _create_rate(self, rate, days_ago, target_currency=USD):
        obj = RscExchangeRate.objects.create(
            rate=rate,
            real_rate=rate,
            price_source="COIN_GECKO",
            target_currency=target_currency,
        )
        # Bypass auto_now_add so we can backdate for the test.
        backdated = timezone.now() - timedelta(days=days_ago)
        RscExchangeRate.objects.filter(pk=obj.pk).update(created_date=backdated)
        return obj

    def test_averages_rates_in_window(self):
        self._create_rate(rate=1.0, days_ago=0)
        self._create_rate(rate=2.0, days_ago=1)
        self._create_rate(rate=3.0, days_ago=2)

        self.assertEqual(RscExchangeRate.get_average_rate(days=3), 2.0)

    def test_excludes_rates_outside_window(self):
        # Inside the 3-day window
        self._create_rate(rate=1.0, days_ago=0)
        self._create_rate(rate=2.0, days_ago=2)
        # Outside the window — must be ignored
        self._create_rate(rate=100.0, days_ago=10)

        self.assertEqual(RscExchangeRate.get_average_rate(days=3), 1.5)

    def test_falls_back_to_latest_when_no_rates_in_window(self):
        # Only an old rate exists; window is empty
        self._create_rate(rate=4.2, days_ago=10)

        self.assertEqual(RscExchangeRate.get_average_rate(days=3), 4.2)

    def test_filters_by_target_currency(self):
        self._create_rate(rate=1.0, days_ago=0, target_currency=USD)
        self._create_rate(rate=999.0, days_ago=0, target_currency=ETHER)

        self.assertEqual(RscExchangeRate.get_average_rate(days=3), 1.0)
