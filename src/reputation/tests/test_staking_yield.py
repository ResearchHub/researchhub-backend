from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

from celery.exceptions import MaxRetriesExceededError, Retry
from django.test import TestCase, override_settings

from purchase.models import Balance
from reputation.models import (
    Distribution,
    StakingGlobalSnapshot,
    StakingUserSnapshot,
    StakingYieldRecord,
)
from reputation.services.staking_yield_service import StakingYieldService
from reputation.tasks import (
    create_daily_staking_global_snapshot,
    distribute_staking_yield,
)
from reputation.tests.helpers import create_deposit
from user.tests.helpers import create_random_default_user


class StakingYieldServiceTest(TestCase):
    def _make_snapshot(self, **kwargs):
        defaults = {
            "emission_per_year": Decimal("9500000"),
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

    def test_compute_annualized_rate_basic(self):
        snapshot = self._make_snapshot_with_staking()
        stake = Decimal("1000")
        multiplier = Decimal("1")
        rate = StakingYieldService.compute_annualized_rate(stake, multiplier, snapshot)
        self.assertGreater(rate, Decimal("0"))

    def test_compute_annualized_rate_known_values(self):
        """When a user's stake equals total staked supply, rate simplifies
        to 100 * emission / total_weighted_stake."""
        snapshot = self._make_snapshot_with_staking(
            emission_per_year=Decimal("100"),
            circulating_supply=Decimal("10000"),
            staked_pct=Decimal("10"),  # total staked = 1000
            avg_multiplier=Decimal("1"),
        )
        stake = Decimal("1000")
        multiplier = Decimal("1")
        rate = StakingYieldService.compute_annualized_rate(stake, multiplier, snapshot)
        # 100 * 100 * 1 / 1000 = 10
        self.assertEqual(rate, Decimal("10"))

    def test_compute_annualized_rate_zero_stake(self):
        snapshot = self._make_snapshot(total_weighted_stake=Decimal("0"))
        rate = StakingYieldService.compute_annualized_rate(
            Decimal("0"), Decimal("1"), snapshot
        )
        self.assertEqual(rate, Decimal("0"))

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

    def test_compute_daily_emission(self):
        daily_emission = StakingYieldService.compute_daily_emission(
            Decimal("3650"),
            date(2026, 3, 23),
        )
        self.assertEqual(daily_emission, Decimal("10"))

    def test_compute_daily_emission_leap_year(self):
        daily_emission = StakingYieldService.compute_daily_emission(
            Decimal("3660"),
            date(2028, 3, 23),
        )
        self.assertEqual(daily_emission, Decimal("10"))

    def test_compute_daily_yield_from_pool_share(self):
        daily_yield = StakingYieldService.compute_daily_yield_from_pool_share(
            weighted_stake=Decimal("10000"),
            total_weighted_stake=Decimal("100000"),
            emission_per_year=Decimal("3650"),
            proration=Decimal("1"),
            accrual_date=date(2026, 3, 23),
        )
        self.assertEqual(daily_yield, Decimal("1.00000000"))

    def test_compute_daily_yield_from_pool_share_leap_year(self):
        daily_yield = StakingYieldService.compute_daily_yield_from_pool_share(
            weighted_stake=Decimal("10000"),
            total_weighted_stake=Decimal("100000"),
            emission_per_year=Decimal("3660"),
            proration=Decimal("1"),
            accrual_date=date(2028, 3, 23),
        )
        self.assertEqual(daily_yield, Decimal("1.00000000"))

    def test_annualized_rate_matches_spreadsheet_year0_estimates(self):
        """Verify annualized rate values match the staking yield spreadsheet (Year 0).

        Spreadsheet globals: circ_supply=134,157,343, emission=9,500,000.
        When multiplier=1 and the individual stake is small,
        rate ~ 100 * emission / (circ_supply * staked_pct / 100).
        """
        base = {
            "emission_per_year": Decimal("9500000"),
            "circulating_supply": Decimal("134157343"),
        }
        small_stake = Decimal("1000")
        multiplier = Decimal("1")

        cases = [
            (1, Decimal("708.12")),
            (2, Decimal("354.06")),
            (3, Decimal("236.04")),
            (5, Decimal("141.62")),
            (7, Decimal("101.16")),
            (10, Decimal("70.81")),
            (15, Decimal("47.21")),
        ]

        for pct, expected_rate in cases:
            snapshot = self._make_snapshot_with_staking(
                staked_pct=Decimal(str(pct)), **base
            )
            rate = StakingYieldService.compute_annualized_rate(
                small_stake, multiplier, snapshot
            )
            self.assertAlmostEqual(
                float(rate),
                float(expected_rate),
                places=1,
                msg=f"Rate mismatch at {pct}% staked",
            )

    def test_annualized_rate_matches_spreadsheet_10m_stake_at_10pct(self):
        """With a 10M individual stake at 10% staked, rate should be ~70.81%."""
        snapshot = self._make_snapshot_with_staking(
            emission_per_year=Decimal("9500000"),
            circulating_supply=Decimal("134157343"),
            staked_pct=Decimal("10"),
            avg_multiplier=Decimal("1"),
        )
        rate = StakingYieldService.compute_annualized_rate(
            Decimal("10000000"), Decimal("1"), snapshot
        )
        self.assertAlmostEqual(float(rate), 70.81, places=1)

    def test_yearly_return_from_daily_yields(self):
        """Summing 365 daily yields should approximate stake * rate / 100."""
        snapshot = self._make_snapshot_with_staking(
            emission_per_year=Decimal("9500000"),
            circulating_supply=Decimal("134157343"),
            staked_pct=Decimal("10"),
            avg_multiplier=Decimal("1"),
        )
        stake = Decimal("10000000")
        multiplier = Decimal("1")
        annualized_rate = StakingYieldService.compute_annualized_rate(
            stake,
            multiplier,
            snapshot,
        )
        weighted_stake = StakingYieldService.compute_weighted_stake(stake, multiplier)

        total_yield = Decimal("0")
        for day_offset in range(365):
            accrual = date(2025, 1, 1) + timedelta(days=day_offset)
            daily = StakingYieldService.compute_daily_yield_from_pool_share(
                weighted_stake,
                snapshot.total_weighted_stake,
                snapshot.emission_per_year,
                Decimal("1"),
                accrual,
            )
            total_yield += daily

        expected_annual = stake * annualized_rate / Decimal("100")
        pct_diff = abs(float(total_yield - expected_annual) / float(expected_annual))
        self.assertLess(
            pct_diff,
            0.001,
            f"Yearly yield {total_yield} differs from expected {expected_annual} "
            f"by {pct_diff:.4%}",
        )

    def test_annualized_rate_matches_spreadsheet_year1_estimates(self):
        """Verify rate values match the spreadsheet Year 1 column."""
        base = {
            "emission_per_year": Decimal("9397666"),
            "circulating_supply": Decimal("143657343"),
        }
        small_stake = Decimal("1000")
        multiplier = Decimal("1")

        cases = [
            (1, Decimal("654.17")),
            (5, Decimal("130.83")),
            (10, Decimal("65.42")),
            (15, Decimal("43.61")),
        ]

        for pct, expected_rate in cases:
            snapshot = self._make_snapshot_with_staking(
                staked_pct=Decimal(str(pct)), **base
            )
            rate = StakingYieldService.compute_annualized_rate(
                small_stake, multiplier, snapshot
            )
            self.assertAlmostEqual(
                float(rate),
                float(expected_rate),
                places=1,
                msg=f"Year 1 rate mismatch at {pct}% staked",
            )

    def test_compute_daily_yield_from_pool_share_zero_inputs(self):
        result = StakingYieldService.compute_daily_yield_from_pool_share(
            weighted_stake=Decimal("10000"),
            total_weighted_stake=Decimal("100000"),
            emission_per_year=Decimal("0"),
            proration=Decimal("1"),
        )
        self.assertEqual(result, Decimal("0"))

    def test_compute_daily_yield_from_pool_share_with_proration(self):
        daily_yield = StakingYieldService.compute_daily_yield_from_pool_share(
            weighted_stake=Decimal("10000"),
            total_weighted_stake=Decimal("100000"),
            emission_per_year=Decimal("3650"),
            proration=Decimal("0.50000000"),
            accrual_date=date(2026, 3, 23),
        )
        self.assertEqual(daily_yield, Decimal("0.50000000"))


class CreateDailyStakingSnapshotTaskTest(TestCase):
    def _expected_accrual_date(self):
        return datetime.now(timezone.utc).date() - timedelta(days=1)

    def setUp(self):
        self.config, _ = StakingGlobalSnapshot.objects.update_or_create(
            pk=1,
            defaults={
                "emission_per_year": Decimal("9500000"),
                "circulating_supply": Decimal("215052673"),
            },
        )

    @patch(
        "reputation.services.rsc_supply_service."
        "RscSupplyService.fetch_circulating_supply"
    )
    def test_creates_new_snapshot(self, mock_supply):
        mock_supply.return_value = Decimal("220000000")
        result = create_daily_staking_global_snapshot()

        self.assertTrue(result)
        latest = StakingGlobalSnapshot.load()
        self.assertNotEqual(latest.pk, self.config.pk)
        self.assertEqual(latest.accrual_date, self._expected_accrual_date())
        self.assertEqual(latest.circulating_supply, Decimal("220000000"))
        self.assertEqual(latest.emission_per_year, Decimal("9500000"))

    @patch(
        "reputation.services.rsc_supply_service."
        "RscSupplyService.fetch_circulating_supply"
    )
    def test_creates_snapshot_with_staking_stats(self, mock_supply):
        mock_supply.return_value = Decimal("100000")

        user = create_random_default_user("staker1")
        user.is_staking_opted_in = True
        user.save()
        create_deposit(user, amount="5000")

        create_daily_staking_global_snapshot()
        latest = StakingGlobalSnapshot.load()
        self.assertEqual(latest.total_staked, Decimal("5000"))
        self.assertEqual(latest.total_weighted_stake, Decimal("5000"))

        user_snapshot = StakingUserSnapshot.objects.get(
            global_snapshot=latest,
            user=user,
        )
        self.assertEqual(user_snapshot.stake_amount, Decimal("5000"))
        self.assertEqual(user_snapshot.weighted_stake, Decimal("5000"))

    @patch(
        "reputation.services.rsc_supply_service."
        "RscSupplyService.fetch_circulating_supply"
    )
    def test_excludes_ineligible_users_from_stats(self, mock_supply):
        mock_supply.return_value = Decimal("100000")

        # Opted-out user
        user = create_random_default_user("nonstaker")
        user.is_staking_opted_in = False
        user.save()
        create_deposit(user, amount="5000")

        # Suspended user
        suspended = create_random_default_user("suspended")
        suspended.is_staking_opted_in = True
        suspended.is_suspended = True
        suspended.save()
        create_deposit(suspended, amount="5000")

        create_daily_staking_global_snapshot()
        latest = StakingGlobalSnapshot.load()
        self.assertEqual(latest.total_staked, Decimal("0"))
        self.assertEqual(latest.user_snapshots.count(), 0)

    @patch(
        "reputation.services.rsc_supply_service."
        "RscSupplyService.fetch_circulating_supply"
    )
    def test_inherits_emission_from_previous(self, mock_supply):
        mock_supply.return_value = Decimal("220000000")
        self.config.emission_per_year = Decimal("5000000")
        self.config.save()

        create_daily_staking_global_snapshot()
        latest = StakingGlobalSnapshot.load()
        self.assertEqual(latest.emission_per_year, Decimal("5000000"))

    @patch(
        "reputation.services.rsc_supply_service."
        "RscSupplyService.fetch_circulating_supply"
    )
    def test_snapshot_is_idempotent_per_accrual_date(self, mock_supply):
        mock_supply.return_value = Decimal("220000000")

        create_daily_staking_global_snapshot()
        create_daily_staking_global_snapshot()

        snapshots = StakingGlobalSnapshot.objects.filter(
            accrual_date=self._expected_accrual_date()
        )
        self.assertEqual(snapshots.count(), 1)

    def test_skip_when_no_snapshot_exists(self):
        StakingGlobalSnapshot.objects.all().delete()
        result = create_daily_staking_global_snapshot()
        self.assertFalse(result)

    @patch(
        "reputation.services.rsc_supply_service."
        "RscSupplyService.fetch_circulating_supply"
    )
    @patch("reputation.tasks.create_daily_staking_global_snapshot.retry")
    def test_retries_when_supply_fetch_fails(self, mock_retry, mock_supply):
        mock_supply.side_effect = Exception("CoinGecko unavailable")
        mock_retry.side_effect = Retry()

        with self.assertRaises(Retry):
            create_daily_staking_global_snapshot()

        mock_retry.assert_called_once()
        self.assertEqual(StakingGlobalSnapshot.objects.count(), 1)

    @patch(
        "reputation.services.rsc_supply_service."
        "RscSupplyService.fetch_circulating_supply"
    )
    @patch("reputation.tasks.log_error")
    @patch("reputation.tasks.create_daily_staking_global_snapshot.retry")
    def test_falls_back_to_previous_supply_when_retries_exhausted(
        self, mock_retry, mock_log_error, mock_supply
    ):
        mock_supply.side_effect = Exception("CoinGecko unavailable")
        mock_retry.side_effect = MaxRetriesExceededError()

        result = create_daily_staking_global_snapshot()

        self.assertTrue(result)
        latest = StakingGlobalSnapshot.load()
        self.assertEqual(latest.circulating_supply, self.config.circulating_supply)
        self.assertEqual(latest.accrual_date, self._expected_accrual_date())
        mock_retry.assert_called_once()
        mock_log_error.assert_called_once()


@override_settings(STAGING=True)
class DistributeStakingYieldTaskTest(TestCase):
    def setUp(self):
        self.accrual_date = datetime.now(timezone.utc).date() - timedelta(days=1)
        self.config, _ = StakingGlobalSnapshot.objects.update_or_create(
            pk=1,
            defaults={
                "emission_per_year": Decimal("9500000"),
                "circulating_supply": Decimal("215052673"),
                "total_staked": Decimal("0"),
                "total_weighted_stake": Decimal("0"),
            },
        )
        self.user = create_random_default_user("yielduser")
        self.user.is_staking_opted_in = True
        self.user.staking_opted_in_date = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.user.save()
        create_deposit(self.user, amount="10000")
        self.global_snapshot = StakingGlobalSnapshot.objects.create(
            accrual_date=self.accrual_date,
            emission_per_year=Decimal("9500000"),
            circulating_supply=Decimal("215052673"),
            total_staked=Decimal("10000"),
            total_weighted_stake=Decimal("10000"),
        )
        self.user_snapshot = StakingUserSnapshot.objects.create(
            global_snapshot=self.global_snapshot,
            user=self.user,
            stake_amount=Decimal("10000"),
            multiplier=Decimal("1"),
            weighted_stake=Decimal("10000"),
            staking_opted_in_date=self.user.staking_opted_in_date,
        )

    def test_distributes_yield(self):
        distribute_staking_yield()

        yield_record = StakingYieldRecord.objects.get(
            user=self.user, accrual_date=self.accrual_date
        )
        self.assertGreater(yield_record.yield_amount, Decimal("0"))
        self.assertIsNotNone(yield_record.distribution)
        self.assertEqual(
            yield_record.global_snapshot,
            self.global_snapshot,
        )
        self.assertEqual(yield_record.user_snapshot, self.user_snapshot)
        self.assertEqual(yield_record.stake_amount, Decimal("10000"))

        # Verify distribution is locked
        dist = yield_record.distribution
        self.assertEqual(dist.distribution_type, "STAKING_YIELD")
        self.assertEqual(dist.distributed_status, Distribution.DISTRIBUTED)

        # Verify balance record is locked
        balance = Balance.objects.filter(
            user=self.user,
            object_id=dist.id,
        ).first()
        self.assertIsNotNone(balance)
        self.assertTrue(balance.is_locked)

    def test_idempotent_distribution(self):
        """Running the task twice should not create duplicate
        distributions."""
        distribute_staking_yield()
        distribute_staking_yield()

        yield_records = StakingYieldRecord.objects.filter(
            user=self.user, accrual_date=self.accrual_date
        )
        self.assertEqual(yield_records.count(), 1)

        distributions = Distribution.objects.filter(
            recipient=self.user, distribution_type="STAKING_YIELD"
        )
        self.assertEqual(distributions.count(), 1)

    def test_skip_when_no_snapshot(self):
        StakingGlobalSnapshot.objects.all().delete()
        result = distribute_staking_yield()
        self.assertFalse(result)
        self.assertEqual(StakingYieldRecord.objects.count(), 0)

    def test_uses_snapshot_position_even_if_user_state_changes_after_snapshot(self):
        Balance.objects.filter(user=self.user).delete()
        self.user.is_staking_opted_in = False
        self.user.staking_opted_in_date = None
        self.user.save(update_fields=["is_staking_opted_in", "staking_opted_in_date"])

        distribute_staking_yield()
        yield_record = StakingYieldRecord.objects.get(
            user=self.user,
            accrual_date=self.accrual_date,
        )
        self.assertEqual(yield_record.stake_amount, Decimal("10000"))
        self.assertGreater(yield_record.yield_amount, Decimal("0"))

    def test_skips_currently_suspended_user(self):
        self.user.is_suspended = True
        self.user.save(update_fields=["is_suspended"])

        distribute_staking_yield()
        self.assertEqual(StakingYieldRecord.objects.count(), 0)
