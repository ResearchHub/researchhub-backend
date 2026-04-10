import math
from datetime import date, timedelta
from decimal import ROUND_DOWN, Decimal
from unittest.mock import patch

from django.test import TestCase

from reputation.models import StakingGlobalSnapshot
from reputation.services.staking_yield_service import (
    QUANTIZE_8,
    STAKING_RELEASE_DATE,
    StakingYieldService,
)


class StakingYieldServiceTest(TestCase):
    def _make_snapshot(self, **kwargs):
        defaults = {
            "accrual_date": STAKING_RELEASE_DATE,
            "circulating_supply": Decimal("215052673"),
        }
        defaults.update(kwargs)
        defaults.setdefault("total_staked", Decimal("0"))
        defaults.setdefault("total_weighted_stake", Decimal("0"))
        snapshot, _ = StakingGlobalSnapshot.objects.update_or_create(
            pk=1, defaults=defaults
        )
        return snapshot

    def _make_snapshot_with_staking(self, **kwargs):
        """Helper that computes total_staked/total_weighted_stake from
        staked_pct and circulating_supply."""
        circulating = kwargs.get("circulating_supply", Decimal("215052673"))
        staked_pct = kwargs.pop("staked_pct", Decimal("10"))
        avg_multiplier = kwargs.pop("avg_multiplier", Decimal("1"))
        total_staked = circulating * staked_pct / Decimal("100")
        total_weighted_stake = total_staked * avg_multiplier
        kwargs.setdefault("circulating_supply", circulating)
        kwargs["total_staked"] = total_staked
        kwargs["total_weighted_stake"] = total_weighted_stake
        return self._make_snapshot(**kwargs)

    def test_daily_emission_before_release_date(self):
        emission = StakingYieldService.compute_total_daily_emission(
            STAKING_RELEASE_DATE - timedelta(days=1)
        )
        self.assertEqual(emission, Decimal("0"))

    def test_daily_emission_decreases_over_time(self):
        day1 = StakingYieldService.compute_total_daily_emission(STAKING_RELEASE_DATE)
        day2 = StakingYieldService.compute_total_daily_emission(
            STAKING_RELEASE_DATE + timedelta(days=30)
        )
        day3 = StakingYieldService.compute_total_daily_emission(
            STAKING_RELEASE_DATE + timedelta(days=365)
        )
        self.assertGreater(day1, day2)
        self.assertGreater(day2, day3)

    def test_compute_daily_yield_from_pool_share(self):
        accrual = STAKING_RELEASE_DATE
        daily_emission = StakingYieldService.compute_total_daily_emission(accrual)
        daily_yield = StakingYieldService.compute_daily_yield_from_pool_share(
            weighted_stake=Decimal("10000"),
            total_weighted_stake=Decimal("100000"),
            accrual_date=accrual,
        )
        expected = (daily_emission * Decimal("10000") / Decimal("100000")).quantize(
            QUANTIZE_8, rounding=ROUND_DOWN
        )
        self.assertEqual(daily_yield, expected)

    def test_compute_daily_yield_from_pool_share_before_release(self):
        daily_yield = StakingYieldService.compute_daily_yield_from_pool_share(
            weighted_stake=Decimal("10000"),
            total_weighted_stake=Decimal("100000"),
            accrual_date=STAKING_RELEASE_DATE - timedelta(days=1),
        )
        self.assertEqual(daily_yield, Decimal("0"))

    @patch(
        "reputation.services.staking_yield_service."
        "RscSupplyService.fetch_circulating_supply"
    )
    @patch(
        "reputation.services.staking_yield_service."
        "StakingGlobalSnapshot.load_for_accrual_date"
    )
    def test_create_daily_snapshots_skips_before_release_date(
        self,
        mock_load_snapshot,
        mock_fetch_supply,
    ):
        result = StakingYieldService.create_daily_snapshots(
            STAKING_RELEASE_DATE - timedelta(days=1)
        )

        self.assertIsNone(result)
        mock_load_snapshot.assert_not_called()
        mock_fetch_supply.assert_not_called()

    @patch(
        "reputation.services.staking_yield_service."
        "StakingGlobalSnapshot.load_for_accrual_date"
    )
    def test_distribute_yield_skips_before_release_date(self, mock_load_snapshot):
        result = StakingYieldService.distribute_yield(
            STAKING_RELEASE_DATE - timedelta(days=1)
        )

        self.assertIsNone(result)
        mock_load_snapshot.assert_not_called()

    def test_compute_daily_yield_from_pool_share_zero_inputs(self):
        result = StakingYieldService.compute_daily_yield_from_pool_share(
            weighted_stake=Decimal("0"),
            total_weighted_stake=Decimal("100000"),
            accrual_date=STAKING_RELEASE_DATE,
        )
        self.assertEqual(result, Decimal("0"))

    def test_compute_daily_yield_from_pool_share_rounds_down(self):
        accrual = STAKING_RELEASE_DATE
        daily_emission = StakingYieldService.compute_total_daily_emission(accrual)
        daily_yield = StakingYieldService.compute_daily_yield_from_pool_share(
            weighted_stake=Decimal("1"),
            total_weighted_stake=Decimal("3"),
            accrual_date=accrual,
        )
        expected = (daily_emission / Decimal("3")).quantize(
            QUANTIZE_8, rounding=ROUND_DOWN
        )
        self.assertEqual(daily_yield, expected)

    def test_daily_emission_day_0_matches_spreadsheet(self):
        """Day 0 emission = 9,500,000 / 365 ≈ 26027.39726 RSC."""
        emission = StakingYieldService.compute_total_daily_emission(
            STAKING_RELEASE_DATE
        )
        self.assertAlmostEqual(float(emission), 26027.39726, places=3)

    def test_daily_emission_day_1_matches_spreadsheet(self):
        """Spreadsheet Daily Returns row for day 1: 26026.62498 RSC."""
        emission = StakingYieldService.compute_total_daily_emission(
            STAKING_RELEASE_DATE + timedelta(days=1)
        )
        self.assertAlmostEqual(float(emission), 26026.62498, places=2)

    def test_daily_emission_day_365_matches_spreadsheet(self):
        """Spreadsheet Daily Returns row for day 365: 25747.03048 RSC."""
        emission = StakingYieldService.compute_total_daily_emission(
            STAKING_RELEASE_DATE + timedelta(days=365)
        )
        self.assertAlmostEqual(float(emission), 25747.03048, places=2)

    def test_daily_emission_day_730_matches_spreadsheet(self):
        """Spreadsheet Daily Returns row for day 730: 25469.68381 RSC."""
        emission = StakingYieldService.compute_total_daily_emission(
            STAKING_RELEASE_DATE + timedelta(days=730)
        )
        self.assertAlmostEqual(float(emission), 25469.68381, places=2)
