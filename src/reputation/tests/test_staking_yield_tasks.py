from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

from celery.exceptions import Retry
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


class CreateDailyStakingSnapshotTaskTest(TestCase):
    def setUp(self):
        self.release_date = datetime.now(timezone.utc).date() - timedelta(days=2)
        self.patcher = patch(
            "reputation.services.staking_yield_service.STAKING_RELEASE_DATE",
            self.release_date,
        )
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def _expected_accrual_date(self):
        return datetime.now(timezone.utc).date() - timedelta(days=1)

    @patch(
        "reputation.services.rsc_supply_service."
        "RscSupplyService.fetch_circulating_supply"
    )
    def test_creates_new_snapshot(self, mock_supply):
        mock_supply.return_value = Decimal("220000000")
        result = create_daily_staking_global_snapshot()

        self.assertTrue(result)
        latest = StakingGlobalSnapshot.load()
        self.assertEqual(latest.accrual_date, self._expected_accrual_date())
        self.assertEqual(latest.circulating_supply, Decimal("220000000"))
        self.assertEqual(StakingGlobalSnapshot.objects.count(), 1)

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

        user = create_random_default_user("nonstaker")
        user.is_staking_opted_in = False
        user.save()
        create_deposit(user, amount="5000")

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
    def test_snapshot_is_idempotent_per_accrual_date(self, mock_supply):
        mock_supply.return_value = Decimal("220000000")

        create_daily_staking_global_snapshot()
        create_daily_staking_global_snapshot()

        snapshots = StakingGlobalSnapshot.objects.filter(
            accrual_date=self._expected_accrual_date()
        )
        self.assertEqual(snapshots.count(), 1)

    @patch(
        "reputation.services.rsc_supply_service."
        "RscSupplyService.fetch_circulating_supply"
    )
    def test_creates_first_snapshot_without_seed_row(self, mock_supply):
        mock_supply.return_value = Decimal("220000000")
        result = create_daily_staking_global_snapshot()

        self.assertTrue(result)
        self.assertEqual(StakingGlobalSnapshot.objects.count(), 1)

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
        self.assertEqual(StakingGlobalSnapshot.objects.count(), 0)

    @patch(
        "reputation.services.rsc_supply_service."
        "RscSupplyService.fetch_circulating_supply"
    )
    @patch("reputation.tasks.log_error")
    @patch("reputation.tasks.create_daily_staking_global_snapshot.retry")
    def test_returns_false_and_logs_error_on_final_attempt(
        self, mock_retry, mock_log_error, mock_supply
    ):
        mock_supply.side_effect = Exception("CoinGecko unavailable")

        with patch.object(
            create_daily_staking_global_snapshot.request,
            "retries",
            create_daily_staking_global_snapshot.max_retries,
        ):
            result = create_daily_staking_global_snapshot()

        self.assertFalse(result)
        self.assertEqual(StakingGlobalSnapshot.objects.count(), 0)
        mock_retry.assert_not_called()
        mock_log_error.assert_called_once()


@override_settings(STAGING=True)
class DistributeStakingYieldTaskTest(TestCase):
    def setUp(self):
        self.release_date = datetime.now(timezone.utc).date() - timedelta(days=2)
        self.patcher = patch(
            "reputation.services.staking_yield_service.STAKING_RELEASE_DATE",
            self.release_date,
        )
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

        self.accrual_date = datetime.now(timezone.utc).date() - timedelta(days=1)
        self.user = create_random_default_user("yielduser")
        self.user.is_staking_opted_in = True
        self.user.staking_opted_in_date = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.user.save()
        create_deposit(self.user, amount="10000")
        self.global_snapshot = StakingGlobalSnapshot.objects.create(
            accrual_date=self.accrual_date,
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
        )

    def test_distributes_yield(self):
        distribute_staking_yield()

        yield_record = StakingYieldRecord.objects.get(user_snapshot=self.user_snapshot)
        self.assertGreater(yield_record.yield_amount, Decimal("0"))
        self.assertIsNotNone(yield_record.distribution)
        self.assertEqual(
            yield_record.user_snapshot.global_snapshot,
            self.global_snapshot,
        )
        self.assertEqual(yield_record.user_snapshot, self.user_snapshot)
        self.assertEqual(yield_record.user_snapshot.stake_amount, Decimal("10000"))

        dist = yield_record.distribution
        self.assertEqual(dist.distribution_type, "STAKING_YIELD")
        self.assertEqual(dist.distributed_status, Distribution.DISTRIBUTED)

        balance = Balance.objects.filter(
            user=self.user,
            object_id=dist.id,
        ).first()
        self.assertIsNotNone(balance)
        self.assertTrue(balance.is_locked)

    def test_idempotent_distribution(self):
        distribute_staking_yield()
        distribute_staking_yield()

        yield_records = StakingYieldRecord.objects.filter(
            user_snapshot=self.user_snapshot
        )
        self.assertEqual(yield_records.count(), 1)

        distributions = Distribution.objects.filter(
            recipient=self.user, distribution_type="STAKING_YIELD"
        )
        self.assertEqual(distributions.count(), 1)

    def test_uses_snapshot_even_if_user_state_changes_after_snapshot(self):
        Balance.objects.filter(user=self.user).delete()
        self.user.is_staking_opted_in = False
        self.user.staking_opted_in_date = None
        self.user.save(update_fields=["is_staking_opted_in", "staking_opted_in_date"])

        distribute_staking_yield()
        yield_record = StakingYieldRecord.objects.get(user_snapshot=self.user_snapshot)
        self.assertEqual(yield_record.user_snapshot.stake_amount, Decimal("10000"))
        self.assertGreater(yield_record.yield_amount, Decimal("0"))

    def test_skips_currently_suspended_user(self):
        self.user.is_suspended = True
        self.user.save(update_fields=["is_suspended"])

        distribute_staking_yield()
        self.assertEqual(StakingYieldRecord.objects.count(), 0)

    def test_splits_yield_proportionally_between_two_users(self):
        user2 = create_random_default_user("yielduser2")
        user2.is_staking_opted_in = True
        user2.staking_opted_in_date = datetime(2026, 1, 1, tzinfo=timezone.utc)
        user2.save()
        create_deposit(user2, amount="30000")

        # Update global snapshot to reflect both users' stakes.
        self.global_snapshot.total_staked = Decimal("40000")
        self.global_snapshot.total_weighted_stake = Decimal("40000")
        self.global_snapshot.save()

        user2_snapshot = StakingUserSnapshot.objects.create(
            global_snapshot=self.global_snapshot,
            user=user2,
            stake_amount=Decimal("30000"),
            multiplier=Decimal("1"),
            weighted_stake=Decimal("30000"),
        )

        distribute_staking_yield()

        rec1 = StakingYieldRecord.objects.get(user_snapshot=self.user_snapshot)
        rec2 = StakingYieldRecord.objects.get(user_snapshot=user2_snapshot)

        # user1 has 10k/40k = 25%, user2 has 30k/40k = 75%
        self.assertGreater(rec1.yield_amount, Decimal("0"))
        self.assertGreater(rec2.yield_amount, Decimal("0"))

        expected_daily = StakingYieldService.compute_total_daily_emission(
            self.accrual_date
        )
        expected1 = StakingYieldService.compute_daily_yield_from_pool_share(
            Decimal("10000"), Decimal("40000"), self.accrual_date
        )
        expected2 = StakingYieldService.compute_daily_yield_from_pool_share(
            Decimal("30000"), Decimal("40000"), self.accrual_date
        )

        self.assertEqual(rec1.yield_amount, expected1)
        self.assertEqual(rec2.yield_amount, expected2)

        # 3:1 ratio
        self.assertAlmostEqual(
            float(rec2.yield_amount / rec1.yield_amount), 3.0, places=2
        )

        # Sum should not exceed daily emission
        self.assertLessEqual(rec1.yield_amount + rec2.yield_amount, expected_daily)

    def test_rolls_back_distribution_if_yield_record_save_fails(self):
        yield_record = StakingYieldRecord.objects.create(
            user_snapshot=self.user_snapshot,
            yield_amount=Decimal("0"),
        )

        with patch.object(
            StakingYieldRecord,
            "save",
            autospec=True,
            side_effect=RuntimeError("save failed"),
        ):
            with self.assertRaises(RuntimeError):
                distribute_staking_yield()

        self.assertEqual(
            Distribution.objects.filter(
                recipient=self.user,
                distribution_type="STAKING_YIELD",
            ).count(),
            0,
        )
        self.assertEqual(
            Balance.objects.filter(user=self.user, is_locked=True).count(),
            0,
        )
        yield_record.refresh_from_db()
        self.assertIsNone(yield_record.distribution_id)
