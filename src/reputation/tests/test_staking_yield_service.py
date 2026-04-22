import math
from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_DOWN, Decimal
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from purchase.models import Balance
from reputation.models import StakingGlobalSnapshot
from reputation.services.staking_yield_service import (
    QUANTIZE_8,
    STAKING_RELEASE_DATE,
    StakingYieldService,
)
from user.tests.helpers import create_random_default_user


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


class StakingMultiplierCalculationTest(TestCase):
    def setUp(self):
        self.user = create_random_default_user("staking-multiplier")
        self.content_type = ContentType.objects.get_for_model(StakingGlobalSnapshot)
        self.accrual_date = STAKING_RELEASE_DATE + timedelta(days=30)

    def _timestamp(self, days_before_accrual):
        return datetime.combine(
            self.accrual_date - timedelta(days=days_before_accrual),
            time.min,
            tzinfo=timezone.utc,
        )

    def _create_balance(self, amount, days_before_accrual, is_locked=False, user=None):
        user = user or self.user
        balance = Balance.objects.create(
            user=user,
            amount=str(amount),
            content_type=self.content_type,
            is_locked=is_locked,
        )
        balance.created_date = self._timestamp(days_before_accrual)
        balance.save(update_fields=["created_date"])
        return balance

    def test_get_unlocked_balance_lots_lifo_uses_lifo(self):
        self._create_balance("100", days_before_accrual=20)
        self._create_balance("50", days_before_accrual=5)
        self._create_balance("-60", days_before_accrual=1)

        lots = sorted(
            self.user.get_unlocked_balance_lots_lifo(),
            key=lambda lot: lot.created_date,
        )

        self.assertEqual(len(lots), 1)
        self.assertEqual(lots[0].amount, Decimal("90.00000000"))
        self.assertEqual(lots[0].created_date, self.accrual_date - timedelta(days=20))

    def test_compute_balance_age_multiplier_uses_step_schedule(self):
        self.assertEqual(
            StakingYieldService.compute_balance_age_multiplier(0),
            Decimal("1.00000000"),
        )
        self.assertEqual(
            StakingYieldService.compute_balance_age_multiplier(29),
            Decimal("1.00000000"),
        )
        self.assertEqual(
            StakingYieldService.compute_balance_age_multiplier(30),
            Decimal("1.05000000"),
        )
        self.assertEqual(
            StakingYieldService.compute_balance_age_multiplier(179),
            Decimal("1.05000000"),
        )
        self.assertEqual(
            StakingYieldService.compute_balance_age_multiplier(180),
            Decimal("1.10000000"),
        )
        self.assertEqual(
            StakingYieldService.compute_balance_age_multiplier(364),
            Decimal("1.10000000"),
        )
        self.assertEqual(
            StakingYieldService.compute_balance_age_multiplier(365),
            Decimal("1.25000000"),
        )

    def test_calculate_staking_position_clips_age_to_opt_in_date(self):
        self.user.staking_opted_in_date = self._timestamp(days_before_accrual=200)
        self.user.save(update_fields=["staking_opted_in_date"])
        self._create_balance("100", days_before_accrual=400)

        position = StakingYieldService.calculate_staking_position(
            self.user, self.accrual_date
        )

        expected_multiplier = Decimal("1.10000000")
        self.assertEqual(position.stake_amount, Decimal("100.00000000"))
        self.assertEqual(position.multiplier, expected_multiplier)
        self.assertEqual(
            position.weighted_stake,
            StakingYieldService.compute_weighted_stake(
                Decimal("100.00000000"), expected_multiplier
            ),
        )

    def test_calculate_staking_position_weights_multiple_lots(self):
        self.user.staking_opted_in_date = self._timestamp(days_before_accrual=400)
        self.user.save(update_fields=["staking_opted_in_date"])
        self._create_balance("100", days_before_accrual=200)
        self._create_balance("50", days_before_accrual=40)

        position = StakingYieldService.calculate_staking_position(
            self.user, self.accrual_date
        )

        multiplier_200 = Decimal("1.10000000")
        multiplier_40 = Decimal("1.05000000")
        expected_multiplier = (
            (Decimal("100") * multiplier_200 + Decimal("50") * multiplier_40)
            / Decimal("150")
        ).quantize(QUANTIZE_8, rounding=ROUND_DOWN)

        self.assertEqual(position.stake_amount, Decimal("150.00000000"))
        self.assertEqual(position.multiplier, expected_multiplier)
        self.assertEqual(
            position.weighted_stake,
            StakingYieldService.compute_weighted_stake(
                Decimal("150.00000000"), expected_multiplier
            ),
        )

    def test_compute_global_staking_multiplier(self):
        global_multiplier = StakingYieldService.compute_global_staking_multiplier(
            total_staked=Decimal("150"),
            total_weighted_stake=Decimal("157.50000000"),
        )

        self.assertEqual(global_multiplier, Decimal("1.05000000"))

    @patch(
        "reputation.services.staking_yield_service."
        "RscSupplyService.fetch_circulating_supply"
    )
    def test_create_daily_snapshots_applies_age_based_multiplier(self, mock_supply):
        mock_supply.return_value = Decimal("220000000")
        self.user.is_staking_opted_in = True
        self.user.staking_opted_in_date = self._timestamp(days_before_accrual=400)
        self.user.save(update_fields=["is_staking_opted_in", "staking_opted_in_date"])
        self._create_balance("100", days_before_accrual=200)

        user2 = create_random_default_user("staking-multiplier-2")
        user2.is_staking_opted_in = True
        user2.staking_opted_in_date = self._timestamp(days_before_accrual=400)
        user2.save(update_fields=["is_staking_opted_in", "staking_opted_in_date"])
        self._create_balance("50", days_before_accrual=40, user=user2)

        snapshot = StakingYieldService.create_daily_snapshots(self.accrual_date)
        user_snapshot = snapshot.user_snapshots.get(user=self.user)
        user2_snapshot = snapshot.user_snapshots.get(user=user2)

        self.assertEqual(user_snapshot.stake_amount, Decimal("100.00000000"))
        self.assertEqual(user_snapshot.multiplier, Decimal("1.10000000"))
        self.assertEqual(user_snapshot.weighted_stake, Decimal("110.00000000"))
        self.assertEqual(user2_snapshot.stake_amount, Decimal("50.00000000"))
        self.assertEqual(user2_snapshot.multiplier, Decimal("1.05000000"))
        self.assertEqual(user2_snapshot.weighted_stake, Decimal("52.50000000"))
        self.assertEqual(snapshot.total_staked, Decimal("150.00000000"))
        self.assertEqual(snapshot.total_weighted_stake, Decimal("162.50000000"))

    @patch(
        "reputation.services.staking_yield_service."
        "RscSupplyService.fetch_circulating_supply"
    )
    def test_create_daily_snapshots_equal_multipliers_preserve_stake_share(
        self, mock_supply
    ):
        mock_supply.return_value = Decimal("220000000")
        self.user.is_staking_opted_in = True
        self.user.staking_opted_in_date = self._timestamp(days_before_accrual=400)
        self.user.save(update_fields=["is_staking_opted_in", "staking_opted_in_date"])
        self._create_balance("100", days_before_accrual=40)

        user2 = create_random_default_user("staking-equal-multiplier-2")
        user2.is_staking_opted_in = True
        user2.staking_opted_in_date = self._timestamp(days_before_accrual=400)
        user2.save(update_fields=["is_staking_opted_in", "staking_opted_in_date"])
        self._create_balance("50", days_before_accrual=40, user=user2)

        snapshot = StakingYieldService.create_daily_snapshots(self.accrual_date)
        user_snapshot = snapshot.user_snapshots.get(user=self.user)
        user2_snapshot = snapshot.user_snapshots.get(user=user2)

        self.assertEqual(user_snapshot.multiplier, Decimal("1.05000000"))
        self.assertEqual(user2_snapshot.multiplier, user_snapshot.multiplier)
        self.assertEqual(snapshot.total_staked, Decimal("150.00000000"))
        self.assertEqual(snapshot.total_weighted_stake, Decimal("157.50000000"))
        self.assertEqual(
            user_snapshot.weighted_stake / snapshot.total_weighted_stake,
            user_snapshot.stake_amount / snapshot.total_staked,
        )
        self.assertEqual(
            user2_snapshot.weighted_stake / snapshot.total_weighted_stake,
            user2_snapshot.stake_amount / snapshot.total_staked,
        )
