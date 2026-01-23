from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone
from rest_framework.test import APITestCase

from purchase.models import BalanceEntryDate, FundingCredit, StakingSnapshot
from purchase.services.staking_service import StakingService
from user.tests.helpers import create_random_authenticated_user


class TestStakingService(APITestCase):
    def setUp(self):
        self.service = StakingService()
        self.user = create_random_authenticated_user("staking_test")

    def _create_balance_entry(self, user, amount, days_ago=0):
        """Helper to create a BalanceEntryDate record."""
        entry_date = timezone.now() - timedelta(days=days_ago)
        return BalanceEntryDate.objects.create(
            user=user,
            balance=None,
            entry_date=entry_date,
            original_amount=Decimal(str(amount)),
            remaining_amount=Decimal(str(amount)),
        )

    def test_get_multiplier_for_days_tier_1(self):
        """Test 0-30 days gets 1.0x multiplier."""
        self.assertEqual(self.service.get_multiplier_for_days(0), Decimal("1.0"))
        self.assertEqual(self.service.get_multiplier_for_days(15), Decimal("1.0"))
        self.assertEqual(self.service.get_multiplier_for_days(29), Decimal("1.0"))

    def test_get_multiplier_for_days_tier_2(self):
        """Test 30-90 days gets 2.5x multiplier."""
        self.assertEqual(self.service.get_multiplier_for_days(30), Decimal("2.5"))
        self.assertEqual(self.service.get_multiplier_for_days(60), Decimal("2.5"))
        self.assertEqual(self.service.get_multiplier_for_days(89), Decimal("2.5"))

    def test_get_multiplier_for_days_tier_3(self):
        """Test 90-180 days gets 4.0x multiplier."""
        self.assertEqual(self.service.get_multiplier_for_days(90), Decimal("4.0"))
        self.assertEqual(self.service.get_multiplier_for_days(120), Decimal("4.0"))
        self.assertEqual(self.service.get_multiplier_for_days(179), Decimal("4.0"))

    def test_get_multiplier_for_days_tier_4(self):
        """Test 180-365 days gets 6.0x multiplier."""
        self.assertEqual(self.service.get_multiplier_for_days(180), Decimal("6.0"))
        self.assertEqual(self.service.get_multiplier_for_days(270), Decimal("6.0"))
        self.assertEqual(self.service.get_multiplier_for_days(364), Decimal("6.0"))

    def test_get_multiplier_for_days_tier_5(self):
        """Test 365+ days gets 7.5x multiplier."""
        self.assertEqual(self.service.get_multiplier_for_days(365), Decimal("7.5"))
        self.assertEqual(self.service.get_multiplier_for_days(500), Decimal("7.5"))
        self.assertEqual(self.service.get_multiplier_for_days(1000), Decimal("7.5"))

    def test_get_tier_name(self):
        """Test tier name mapping."""
        self.assertEqual(self.service.get_tier_name(Decimal("1.0")), "Bronze")
        self.assertEqual(self.service.get_tier_name(Decimal("2.5")), "Silver")
        self.assertEqual(self.service.get_tier_name(Decimal("4.0")), "Gold")
        self.assertEqual(self.service.get_tier_name(Decimal("6.0")), "Platinum")
        self.assertEqual(self.service.get_tier_name(Decimal("7.5")), "Diamond")

    def test_get_days_until_next_tier(self):
        """Test days until next tier calculation."""
        # At tier 1 (0-30), next tier at 30
        self.assertEqual(self.service.get_days_until_next_tier(0), 30)
        self.assertEqual(self.service.get_days_until_next_tier(15), 15)
        self.assertEqual(self.service.get_days_until_next_tier(29), 1)

        # At tier 2 (30-90), next tier at 90
        self.assertEqual(self.service.get_days_until_next_tier(30), 60)

        # At tier 5 (365+), no next tier
        self.assertIsNone(self.service.get_days_until_next_tier(365))
        self.assertIsNone(self.service.get_days_until_next_tier(1000))

    def test_calculate_user_weighted_balance_no_balance(self):
        """Test weighted balance for user with no balance."""
        balance, multiplier, weighted = self.service.calculate_user_weighted_balance(
            self.user, date.today()
        )
        self.assertEqual(balance, Decimal("0"))
        self.assertEqual(multiplier, Decimal("1.0"))
        self.assertEqual(weighted, Decimal("0"))

    def test_calculate_user_weighted_balance_single_entry(self):
        """Test weighted balance with a single balance entry."""
        self._create_balance_entry(self.user, 1000, days_ago=45)

        balance, multiplier, weighted = self.service.calculate_user_weighted_balance(
            self.user, date.today()
        )

        self.assertEqual(balance, Decimal("1000"))
        self.assertEqual(multiplier, Decimal("2.5"))  # 45 days = tier 2
        self.assertEqual(weighted, Decimal("2500"))  # 1000 * 2.5

    def test_calculate_user_weighted_balance_multiple_entries(self):
        """Test weighted balance with multiple balance entries at different ages."""
        # Old entry (400 days) = tier 5 (7.5x)
        self._create_balance_entry(self.user, 1000, days_ago=400)
        # Recent entry (10 days) = tier 1 (1.0x)
        self._create_balance_entry(self.user, 1000, days_ago=10)

        balance, multiplier, weighted = self.service.calculate_user_weighted_balance(
            self.user, date.today()
        )

        # Total balance = 2000
        self.assertEqual(balance, Decimal("2000"))
        # Weighted = (1000 * 7.5) + (1000 * 1.0) = 8500
        self.assertEqual(weighted, Decimal("8500"))
        # Effective multiplier = 8500 / 2000 = 4.25
        self.assertEqual(multiplier, Decimal("4.25"))

    def test_create_daily_snapshot(self):
        """Test creating a daily snapshot for a user."""
        self._create_balance_entry(self.user, 500, days_ago=100)

        snapshot = self.service.create_daily_snapshot(self.user, date.today())

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.user, self.user)
        self.assertEqual(snapshot.snapshot_date, date.today())
        self.assertEqual(snapshot.rsc_balance, Decimal("500"))
        self.assertEqual(snapshot.multiplier, Decimal("4.0"))  # 100 days = tier 3
        self.assertEqual(snapshot.weighted_balance, Decimal("2000"))

    def test_create_daily_snapshot_below_minimum(self):
        """Test that users below minimum balance don't get snapshots."""
        # Create balance below minimum (100 RSC)
        self._create_balance_entry(self.user, 50, days_ago=10)

        snapshot = self.service.create_daily_snapshot(self.user, date.today())

        self.assertIsNone(snapshot)

    def test_create_daily_snapshot_updates_existing(self):
        """Test that creating a snapshot updates existing one for same date."""
        self._create_balance_entry(self.user, 500, days_ago=100)

        # Create first snapshot
        snapshot1 = self.service.create_daily_snapshot(self.user, date.today())

        # Add more balance
        self._create_balance_entry(self.user, 500, days_ago=50)

        # Create second snapshot for same date
        snapshot2 = self.service.create_daily_snapshot(self.user, date.today())

        # Should be the same record, updated
        self.assertEqual(snapshot1.id, snapshot2.id)
        self.assertEqual(snapshot2.rsc_balance, Decimal("1000"))

    def test_handle_withdrawal_fifo(self):
        """Test FIFO withdrawal handling - newest RSC withdrawn first."""
        # Create entries: old (100 days) and new (10 days)
        old_entry = self._create_balance_entry(self.user, 1000, days_ago=100)
        new_entry = self._create_balance_entry(self.user, 1000, days_ago=10)

        # Withdraw 500 - should come from new entry first (FIFO = newest first)
        self.service.handle_withdrawal_fifo(self.user, Decimal("500"))

        old_entry.refresh_from_db()
        new_entry.refresh_from_db()

        # New entry should be reduced, old entry untouched
        self.assertEqual(new_entry.remaining_amount, Decimal("500"))
        self.assertEqual(old_entry.remaining_amount, Decimal("1000"))

    def test_handle_withdrawal_fifo_spans_entries(self):
        """Test FIFO withdrawal that spans multiple entries."""
        old_entry = self._create_balance_entry(self.user, 1000, days_ago=100)
        new_entry = self._create_balance_entry(self.user, 500, days_ago=10)

        # Withdraw 700 - should use all of new (500) + some of old (200)
        self.service.handle_withdrawal_fifo(self.user, Decimal("700"))

        old_entry.refresh_from_db()
        new_entry.refresh_from_db()

        # New entry should be depleted
        self.assertEqual(new_entry.remaining_amount, Decimal("0"))
        # Old entry should be reduced by 200
        self.assertEqual(old_entry.remaining_amount, Decimal("800"))

    def test_get_user_staking_info(self):
        """Test getting complete staking info for a user."""
        self._create_balance_entry(self.user, 1000, days_ago=200)

        info = self.service.get_user_staking_info(self.user)

        self.assertEqual(info["rsc_balance"], Decimal("1000"))
        self.assertEqual(info["current_multiplier"], Decimal("6.0"))  # 200 days
        self.assertEqual(info["multiplier_tier"], "Platinum")
        self.assertEqual(info["days_held"], 200)
        # Days until next tier (365 - 200 = 165)
        self.assertEqual(info["days_until_next_tier"], 165)
        self.assertIn("projected_weekly_credits", info)
        self.assertIn("projected_apy", info)


class TestStakingDistribution(APITestCase):
    def setUp(self):
        self.service = StakingService()
        self.user1 = create_random_authenticated_user("staker1")
        self.user2 = create_random_authenticated_user("staker2")

    def _create_balance_entry(self, user, amount, days_ago=0):
        """Helper to create a BalanceEntryDate record."""
        entry_date = timezone.now() - timedelta(days=days_ago)
        return BalanceEntryDate.objects.create(
            user=user,
            balance=None,
            entry_date=entry_date,
            original_amount=Decimal(str(amount)),
            remaining_amount=Decimal(str(amount)),
        )

    def test_create_all_user_snapshots(self):
        """Test batch creating snapshots for all users."""
        self._create_balance_entry(self.user1, 500, days_ago=50)
        self._create_balance_entry(self.user2, 1000, days_ago=100)

        count = self.service.create_all_user_snapshots(date.today())

        self.assertEqual(count, 2)
        self.assertEqual(
            StakingSnapshot.objects.filter(snapshot_date=date.today()).count(), 2
        )

    def test_distribute_weekly_rewards(self):
        """Test weekly reward distribution."""
        today = date.today()
        yesterday = today - timedelta(days=1)

        # Create snapshots for yesterday
        self._create_balance_entry(self.user1, 500, days_ago=50)
        self._create_balance_entry(self.user2, 500, days_ago=50)

        self.service.create_all_user_snapshots(yesterday)

        # Distribute rewards
        record = self.service.distribute_weekly_rewards(today)

        self.assertEqual(record.status, "COMPLETED")
        self.assertEqual(record.users_rewarded, 2)

        # Check funding credits were created
        user1_credits = FundingCredit.objects.filter(user=self.user1)
        user2_credits = FundingCredit.objects.filter(user=self.user2)

        self.assertEqual(user1_credits.count(), 1)
        self.assertEqual(user2_credits.count(), 1)

        # Both have same weighted balance, so should get equal share
        self.assertEqual(
            user1_credits.first().amount, user2_credits.first().amount
        )

    def test_distribute_weekly_rewards_no_duplicate(self):
        """Test that distribution doesn't happen twice for same date."""
        today = date.today()
        yesterday = today - timedelta(days=1)

        self._create_balance_entry(self.user1, 500, days_ago=50)
        self.service.create_all_user_snapshots(yesterday)

        # First distribution
        record1 = self.service.distribute_weekly_rewards(today)
        # Second distribution (should return existing)
        record2 = self.service.distribute_weekly_rewards(today)

        self.assertEqual(record1.id, record2.id)
        # User should only have 1 credit record
        self.assertEqual(FundingCredit.objects.filter(user=self.user1).count(), 1)
