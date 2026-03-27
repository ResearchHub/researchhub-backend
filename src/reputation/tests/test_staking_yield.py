import math
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_DOWN, Decimal
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
from reputation.services.staking_yield_service import (
    HALVING_PERIOD_DAYS,
    HUNDRED,
    INITIAL_DAILY_EMISSION,
    QUANTIZE_8,
    STAKING_RELEASE_DATE,
    StakingYieldService,
    days_in_year,
)
from reputation.tasks import (
    create_daily_staking_global_snapshot,
    distribute_staking_yield,
)
from reputation.tests.helpers import create_deposit
from user.tests.helpers import create_random_default_user


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

    # --- compute_total_daily_emission tests ---

    def test_daily_emission_on_release_date(self):
        """On day 0, daily emission equals the initial value."""
        emission = StakingYieldService.compute_total_daily_emission(
            STAKING_RELEASE_DATE
        )
        self.assertEqual(emission, INITIAL_DAILY_EMISSION)

    def test_daily_emission_before_release_date(self):
        """Before release, emission is 0."""
        emission = StakingYieldService.compute_total_daily_emission(
            STAKING_RELEASE_DATE - timedelta(days=1)
        )
        self.assertEqual(emission, Decimal("0"))

    def test_daily_emission_halves_after_64_years(self):
        """After exactly 64 years (HALVING_PERIOD_DAYS), emission halves."""
        future = STAKING_RELEASE_DATE + timedelta(days=HALVING_PERIOD_DAYS)
        emission = StakingYieldService.compute_total_daily_emission(future)
        expected = (INITIAL_DAILY_EMISSION / Decimal("2")).quantize(
            QUANTIZE_8, rounding=ROUND_DOWN
        )
        self.assertEqual(emission, expected)

    def test_daily_emission_after_one_year(self):
        """After 1 year, emission matches the formula."""
        one_year_later = STAKING_RELEASE_DATE + timedelta(days=365)
        emission = StakingYieldService.compute_total_daily_emission(one_year_later)
        exponent = 365 / HALVING_PERIOD_DAYS
        expected = (
            INITIAL_DAILY_EMISSION / Decimal(str(math.pow(2, exponent)))
        ).quantize(QUANTIZE_8, rounding=ROUND_DOWN)
        self.assertEqual(emission, expected)

    def test_daily_emission_decreases_over_time(self):
        """Emission strictly decreases day over day."""
        day1 = StakingYieldService.compute_total_daily_emission(STAKING_RELEASE_DATE)
        day2 = StakingYieldService.compute_total_daily_emission(
            STAKING_RELEASE_DATE + timedelta(days=30)
        )
        day3 = StakingYieldService.compute_total_daily_emission(
            STAKING_RELEASE_DATE + timedelta(days=365)
        )
        self.assertGreater(day1, day2)
        self.assertGreater(day2, day3)

    # --- compute_annualized_rate tests ---

    def test_compute_annualized_rate_basic(self):
        snapshot = self._make_snapshot_with_staking()
        stake = Decimal("1000")
        multiplier = Decimal("1")
        rate = StakingYieldService.compute_annualized_rate(stake, multiplier, snapshot)
        self.assertGreater(rate, Decimal("0"))

    def test_compute_annualized_rate_known_values(self):
        """When a user's stake equals total staked supply, rate simplifies
        to 100 * daily_emission * days_in_year * multiplier / total_weighted_stake."""
        snapshot = self._make_snapshot_with_staking(
            accrual_date=STAKING_RELEASE_DATE,
            circulating_supply=Decimal("10000"),
            staked_pct=Decimal("10"),  # total staked = 1000
            avg_multiplier=Decimal("1"),
        )
        stake = Decimal("1000")
        multiplier = Decimal("1")
        rate = StakingYieldService.compute_annualized_rate(stake, multiplier, snapshot)

        # On release date, daily emission = 9500000
        # emission_per_year = 9500000 * 365 = 3467500000
        # rate = 100 * 3467500000 * 1 / 1000 = 346750000
        daily = StakingYieldService.compute_total_daily_emission(STAKING_RELEASE_DATE)
        expected = HUNDRED * daily * Decimal("365") * multiplier / Decimal("1000")
        self.assertEqual(rate, expected)

    def test_compute_annualized_rate_zero_stake(self):
        snapshot = self._make_snapshot(total_weighted_stake=Decimal("0"))
        rate = StakingYieldService.compute_annualized_rate(
            Decimal("0"), Decimal("1"), snapshot
        )
        self.assertEqual(rate, Decimal("0"))

    # --- proration tests ---

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

    # --- compute_daily_yield_from_pool_share tests ---

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
        """Before release date, yield is 0."""
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

    # --- spreadsheet / annualized rate tests ---

    def test_annualized_rate_scales_with_staked_pct(self):
        """Higher staked percentage means lower individual rate."""
        base = {
            "circulating_supply": Decimal("134157343"),
            "accrual_date": STAKING_RELEASE_DATE,
        }
        stake = Decimal("1000")
        multiplier = Decimal("1")

        rates = []
        for pct in [1, 5, 10, 15]:
            snapshot = self._make_snapshot_with_staking(
                staked_pct=Decimal(str(pct)), **base
            )
            rate = StakingYieldService.compute_annualized_rate(
                stake, multiplier, snapshot
            )
            rates.append(rate)

        # Rates should be strictly decreasing as staked pct increases
        for i in range(len(rates) - 1):
            self.assertGreater(rates[i], rates[i + 1])

    def test_yearly_return_from_daily_yields(self):
        """Summing daily yields over a year should approximate
        the annualized return, accounting for daily emission decay."""
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

        # Total yield should be positive and reasonable
        self.assertGreater(total_yield, Decimal("0"))
        # Yield should be less than total emission for the year
        # (user doesn't own 100% of the pool)
        total_emission = sum(
            StakingYieldService.compute_total_daily_emission(
                accrual_start + timedelta(days=d)
            )
            for d in range(365)
        )
        self.assertLess(total_yield, total_emission)


@patch(
    "reputation.services.staking_yield_service.STAKING_RELEASE_DATE",
    date(2020, 1, 1),
)
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
        # emission_per_year is computed from the halving formula
        self.assertGreater(latest.emission_per_year, Decimal("0"))

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
    def test_emission_computed_from_halving_formula(self, mock_supply):
        mock_supply.return_value = Decimal("220000000")

        create_daily_staking_global_snapshot()
        latest = StakingGlobalSnapshot.load()
        accrual = latest.accrual_date

        daily = StakingYieldService.compute_total_daily_emission(accrual)
        expected_annual = daily * Decimal(str(days_in_year(accrual.year)))
        self.assertEqual(latest.emission_per_year, expected_annual)

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
@patch(
    "reputation.services.staking_yield_service.STAKING_RELEASE_DATE",
    date(2020, 1, 1),
)
class DistributeStakingYieldTaskTest(TestCase):
    def setUp(self):
        self.accrual_date = datetime.now(timezone.utc).date() - timedelta(days=1)
        daily = StakingYieldService.compute_total_daily_emission(self.accrual_date)
        annual = daily * Decimal(str(days_in_year(self.accrual_date.year)))
        self.config, _ = StakingGlobalSnapshot.objects.update_or_create(
            pk=1,
            defaults={
                "emission_per_year": annual,
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
            emission_per_year=annual,
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
