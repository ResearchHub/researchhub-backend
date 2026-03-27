import math
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_DOWN, Decimal

from django.test import TestCase

from reputation.models import StakingGlobalSnapshot
from reputation.services.staking_yield_service import (
    HALVING_PERIOD_DAYS,
    INITIAL_DAILY_EMISSION,
    QUANTIZE_8,
    STAKING_RELEASE_DATE,
    StakingYieldService,
)


class StakingYieldServiceTest(TestCase):
    def _make_snapshot(self, **kwargs):
        defaults = {
            "accrual_date": STAKING_RELEASE_DATE,
            "emission_per_year": Decimal("0"),
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

    def test_daily_emission_on_release_date(self):
        emission = StakingYieldService.compute_total_daily_emission(
            STAKING_RELEASE_DATE
        )
        self.assertEqual(emission, INITIAL_DAILY_EMISSION)

    def test_daily_emission_before_release_date(self):
        emission = StakingYieldService.compute_total_daily_emission(
            STAKING_RELEASE_DATE - timedelta(days=1)
        )
        self.assertEqual(emission, Decimal("0"))

    def test_daily_emission_halves_after_64_years(self):
        future = STAKING_RELEASE_DATE + timedelta(days=HALVING_PERIOD_DAYS)
        emission = StakingYieldService.compute_total_daily_emission(future)
        expected = (INITIAL_DAILY_EMISSION / Decimal("2")).quantize(
            QUANTIZE_8, rounding=ROUND_DOWN
        )
        self.assertEqual(emission, expected)

    def test_daily_emission_after_one_year(self):
        one_year_later = STAKING_RELEASE_DATE + timedelta(days=365)
        emission = StakingYieldService.compute_total_daily_emission(one_year_later)
        exponent = 365 / HALVING_PERIOD_DAYS
        expected = (
            INITIAL_DAILY_EMISSION / Decimal(str(math.pow(2, exponent)))
        ).quantize(QUANTIZE_8, rounding=ROUND_DOWN)
        self.assertEqual(emission, expected)

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

    def test_compute_proration_full_day(self):
        opted_in = datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc)
        accrual = date(2026, 3, 23)
        proration = StakingYieldService.compute_proration(opted_in, accrual)
        self.assertEqual(proration, Decimal("1"))

    def test_compute_proration_mid_day(self):
        opted_in = datetime(2026, 3, 23, 12, 0, tzinfo=timezone.utc)
        accrual = date(2026, 3, 23)
        proration = StakingYieldService.compute_proration(opted_in, accrual)
        self.assertEqual(proration, Decimal("0.50000000"))

    def test_compute_proration_after_day(self):
        opted_in = datetime(2026, 3, 24, 12, 0, tzinfo=timezone.utc)
        accrual = date(2026, 3, 23)
        proration = StakingYieldService.compute_proration(opted_in, accrual)
        self.assertEqual(proration, Decimal("0"))

    def test_compute_proration_none_opted_in_date(self):
        proration = StakingYieldService.compute_proration(None, date(2026, 3, 23))
        self.assertEqual(proration, Decimal("1"))

    def test_compute_daily_yield_from_pool_share(self):
        accrual = STAKING_RELEASE_DATE
        daily_emission = StakingYieldService.compute_total_daily_emission(accrual)
        daily_yield = StakingYieldService.compute_daily_yield_from_pool_share(
            weighted_stake=Decimal("10000"),
            total_weighted_stake=Decimal("100000"),
            proration=Decimal("1"),
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
            proration=Decimal("1"),
            accrual_date=STAKING_RELEASE_DATE - timedelta(days=1),
        )
        self.assertEqual(daily_yield, Decimal("0"))

    def test_compute_daily_yield_from_pool_share_zero_inputs(self):
        result = StakingYieldService.compute_daily_yield_from_pool_share(
            weighted_stake=Decimal("0"),
            total_weighted_stake=Decimal("100000"),
            proration=Decimal("1"),
            accrual_date=STAKING_RELEASE_DATE,
        )
        self.assertEqual(result, Decimal("0"))

    def test_compute_daily_yield_from_pool_share_with_proration(self):
        accrual = STAKING_RELEASE_DATE
        daily_emission = StakingYieldService.compute_total_daily_emission(accrual)
        daily_yield = StakingYieldService.compute_daily_yield_from_pool_share(
            weighted_stake=Decimal("10000"),
            total_weighted_stake=Decimal("100000"),
            proration=Decimal("0.50000000"),
            accrual_date=accrual,
        )
        expected = (
            daily_emission
            * Decimal("10000")
            / Decimal("100000")
            * Decimal("0.50000000")
        ).quantize(QUANTIZE_8, rounding=ROUND_DOWN)
        self.assertEqual(daily_yield, expected)

    def test_yearly_return_from_daily_yields(self):
        accrual_start = STAKING_RELEASE_DATE
        snapshot = self._make_snapshot_with_staking(
            accrual_date=accrual_start,
            circulating_supply=Decimal("134157343"),
            staked_pct=Decimal("10"),
            avg_multiplier=Decimal("1"),
        )
        stake = Decimal("10000000")
        multiplier = Decimal("1")
        weighted_stake = StakingYieldService.compute_weighted_stake(stake, multiplier)

        total_yield = Decimal("0")
        for day_offset in range(365):
            accrual = accrual_start + timedelta(days=day_offset)
            daily = StakingYieldService.compute_daily_yield_from_pool_share(
                weighted_stake,
                snapshot.total_weighted_stake,
                Decimal("1"),
                accrual,
            )
            total_yield += daily

        self.assertGreater(total_yield, Decimal("0"))
        total_emission = sum(
            StakingYieldService.compute_total_daily_emission(
                accrual_start + timedelta(days=d)
            )
            for d in range(365)
        )
        self.assertLess(total_yield, total_emission)
