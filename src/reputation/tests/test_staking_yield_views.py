from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from rest_framework.test import APIClient, APITestCase

from purchase.models import Balance
from reputation.models import (
    StakingGlobalSnapshot,
    StakingUserSnapshot,
    StakingYieldRecord,
)
from reputation.services.staking_yield_service import StakingYieldService
from user.tests.helpers import create_random_default_user


class StakingYieldViewSetTestBase(APITestCase):
    def setUp(self):
        self.user = create_random_default_user("stakeview")
        self.user.is_staking_opted_in = True
        self.user.save()
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _create_snapshot_with_yield(self, accrual_date, stake, yield_amount):
        global_snapshot = StakingGlobalSnapshot.objects.create(
            accrual_date=accrual_date,
            circulating_supply=Decimal("215052673"),
            total_staked=stake,
            total_weighted_stake=stake,
        )
        user_snapshot = StakingUserSnapshot.objects.create(
            global_snapshot=global_snapshot,
            user=self.user,
            stake_amount=stake,
            multiplier=Decimal("1"),
            weighted_stake=stake,
        )
        StakingYieldRecord.objects.create(
            user_snapshot=user_snapshot,
            yield_amount=yield_amount,
        )
        return global_snapshot


class StakingYieldDetailsTest(StakingYieldViewSetTestBase):
    def test_unauthenticated_returns_401(self):
        client = APIClient()
        resp = client.get("/api/staking_yield/details/")
        self.assertEqual(resp.status_code, 401)

    def test_no_snapshots_returns_zeroes(self):
        resp = self.client.get("/api/staking_yield/details/")
        self.assertEqual(resp.status_code, 200)
        data = resp.data
        self.assertTrue(data["is_staking_opted_in"])
        self.assertIsNotNone(data["staking_opted_in_date"])
        self.assertEqual(Decimal(data["current_stake"]), Decimal("0"))
        self.assertEqual(Decimal(data["current_multiplier"]), Decimal("0"))
        self.assertEqual(Decimal(data["current_weighted_stake"]), Decimal("0"))
        self.assertEqual(Decimal(data["total_yield_earned"]), Decimal("0"))
        self.assertIsNone(data["latest_accrual_date"])
        self.assertEqual(Decimal(data["apy"]), Decimal("0"))
        self.assertEqual(list(data["balance_lots"]), [])

    def test_returns_correct_details(self):
        accrual = date(2026, 4, 15)
        total_staked = Decimal("10000000")
        self._create_snapshot_with_yield(accrual, total_staked, Decimal("100"))

        resp = self.client.get("/api/staking_yield/details/")
        self.assertEqual(resp.status_code, 200)
        data = resp.data
        self.assertEqual(Decimal(data["current_stake"]), total_staked)
        self.assertEqual(Decimal(data["current_multiplier"]), Decimal("1"))
        self.assertEqual(Decimal(data["current_weighted_stake"]), total_staked)
        self.assertEqual(Decimal(data["total_yield_earned"]), Decimal("100"))
        self.assertEqual(data["latest_accrual_date"], "2026-04-15")

        # APY should reflect the global snapshot for this accrual date
        daily_emission = StakingYieldService.compute_total_daily_emission(accrual)
        expected_apy = float(daily_emission) / float(total_staked) * 365 * 100
        self.assertAlmostEqual(float(data["apy"]), expected_apy, places=4)

    def test_aggregates_across_multiple_days(self):
        self._create_snapshot_with_yield(
            date(2026, 4, 15), Decimal("5000"), Decimal("100")
        )
        self._create_snapshot_with_yield(
            date(2026, 4, 16), Decimal("6000"), Decimal("150")
        )

        resp = self.client.get("/api/staking_yield/details/")
        data = resp.data
        self.assertEqual(Decimal(data["total_yield_earned"]), Decimal("250"))
        # Latest snapshot should be the most recent date
        self.assertEqual(Decimal(data["current_stake"]), Decimal("6000"))
        self.assertEqual(data["latest_accrual_date"], "2026-04-16")

    def test_user_isolation(self):
        self._create_snapshot_with_yield(
            date(2026, 4, 15), Decimal("5000"), Decimal("100")
        )

        other_user = create_random_default_user("other")
        other_client = APIClient()
        other_client.force_authenticate(other_user)

        resp = other_client.get("/api/staking_yield/details/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Decimal(resp.data["total_yield_earned"]), Decimal("0"))


class StakingYieldDetailsBalanceLotsTest(StakingYieldViewSetTestBase):
    def setUp(self):
        super().setUp()
        self.content_type = ContentType.objects.get_for_model(StakingGlobalSnapshot)
        self.today = date(2026, 6, 1)
        # Opt-in well before any lot so effective_start_date == lot.created_date
        self.user.staking_opted_in_date = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.user.save()

    def _create_balance(self, amount, created_offset_days):
        balance = Balance.objects.create(
            user=self.user,
            amount=str(amount),
            content_type=self.content_type,
            is_locked=False,
        )
        created = datetime.combine(
            self.today - timedelta(days=created_offset_days),
            time.min,
            tzinfo=timezone.utc,
        )
        balance.created_date = created
        balance.save(update_fields=["created_date"])
        return balance

    def _get_details(self):
        with patch("reputation.views.staking_yield_view.timezone.now") as mock_now:
            mock_now.return_value = datetime.combine(
                self.today, time.min, tzinfo=timezone.utc
            )
            # Keep django timezone.now compatible for any other code paths
            mock_now.side_effect = None
            return self.client.get("/api/staking_yield/details/")

    def test_returns_lot_with_current_and_next_multiplier(self):
        self._create_balance("100", created_offset_days=10)

        resp = self._get_details()

        self.assertEqual(resp.status_code, 200)
        lots = resp.data["balance_lots"]
        self.assertEqual(len(lots), 1)
        lot = lots[0]
        self.assertEqual(Decimal(lot["amount"]), Decimal("100"))
        self.assertEqual(lot["age_days"], 10)
        self.assertEqual(Decimal(lot["current_multiplier"]), Decimal("1"))
        self.assertEqual(Decimal(lot["next_multiplier"]), Decimal("1.05"))
        self.assertEqual(lot["days_until_next_multiplier"], 20)
        self.assertEqual(lot["next_multiplier_date"], "2026-06-21")
        self.assertEqual(lot["created_date"], "2026-05-22")
        self.assertEqual(lot["effective_start_date"], "2026-05-22")
        # Only lot on its tier transition date — overall == its own multiplier
        self.assertEqual(Decimal(lot["projected_overall_multiplier"]), Decimal("1.05"))

    def test_lot_at_max_tier_has_no_next_multiplier(self):
        self.user.staking_opted_in_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
        self.user.save()
        self._create_balance("100", created_offset_days=400)

        resp = self._get_details()

        lots = resp.data["balance_lots"]
        self.assertEqual(len(lots), 1)
        lot = lots[0]
        self.assertEqual(lot["age_days"], 400)
        self.assertEqual(Decimal(lot["current_multiplier"]), Decimal("1.25"))
        self.assertIsNone(lot["next_multiplier"])
        self.assertIsNone(lot["days_until_next_multiplier"])
        self.assertIsNone(lot["next_multiplier_date"])
        self.assertIsNone(lot["projected_overall_multiplier"])

    def test_effective_start_uses_opt_in_date(self):
        # Lot created long before opt-in; opt-in date should drive age
        self.user.staking_opted_in_date = datetime(2026, 5, 15, tzinfo=timezone.utc)
        self.user.save()
        self._create_balance("100", created_offset_days=400)

        resp = self._get_details()

        lot = resp.data["balance_lots"][0]
        self.assertEqual(lot["effective_start_date"], "2026-05-15")
        self.assertEqual(lot["age_days"], 17)
        self.assertEqual(Decimal(lot["current_multiplier"]), Decimal("1"))

    def test_multiple_lots_returned(self):
        self._create_balance("100", created_offset_days=5)
        self._create_balance("200", created_offset_days=100)

        resp = self._get_details()

        lots = resp.data["balance_lots"]
        self.assertEqual(len(lots), 2)
        amounts = sorted(Decimal(lot["amount"]) for lot in lots)
        self.assertEqual(amounts, [Decimal("100"), Decimal("200")])

    def test_projected_overall_multiplier_weights_all_lots(self):
        # Lot A: 100 RSC, age 25 — hits 30-day tier in 5 days
        self._create_balance("100", created_offset_days=25)
        # Lot B: 300 RSC, age 170 — hits 180-day tier in 10 days
        self._create_balance("300", created_offset_days=170)

        resp = self._get_details()

        lots = {Decimal(lot["amount"]): lot for lot in resp.data["balance_lots"]}

        # On lot A's transition date (+5 days): A at 30d=1.05, B at 175d=1.05
        # Weighted: (100 * 1.05 + 300 * 1.05) / 400 = 1.05
        self.assertEqual(
            Decimal(lots[Decimal("100")]["projected_overall_multiplier"]),
            Decimal("1.05"),
        )

        # On lot B's transition date (+10 days): A at 35d=1.05, B at 180d=1.1
        # Weighted: (100 * 1.05 + 300 * 1.1) / 400 = 1.0875
        self.assertEqual(
            Decimal(lots[Decimal("300")]["projected_overall_multiplier"]),
            Decimal("1.0875"),
        )


class StakingYieldEarnedSinceTest(StakingYieldViewSetTestBase):
    def test_unauthenticated_returns_401(self):
        client = APIClient()
        resp = client.get("/api/staking_yield/earned_since/?date=2026-04-15")
        self.assertEqual(resp.status_code, 401)

    def test_missing_date_returns_400(self):
        resp = self.client.get("/api/staking_yield/earned_since/")
        self.assertEqual(resp.status_code, 400)

    def test_invalid_date_returns_400(self):
        resp = self.client.get("/api/staking_yield/earned_since/?date=not-a-date")
        self.assertEqual(resp.status_code, 400)

    def test_filters_by_date(self):
        self._create_snapshot_with_yield(
            date(2026, 4, 14), Decimal("5000"), Decimal("50")
        )
        self._create_snapshot_with_yield(
            date(2026, 4, 15), Decimal("5000"), Decimal("100")
        )
        self._create_snapshot_with_yield(
            date(2026, 4, 16), Decimal("5000"), Decimal("150")
        )

        resp = self.client.get("/api/staking_yield/earned_since/?date=2026-04-15")
        self.assertEqual(resp.status_code, 200)
        # Should include 4/15 and 4/16 but not 4/14
        self.assertEqual(Decimal(resp.data["yield_earned"]), Decimal("250"))
        self.assertEqual(resp.data["since_date"], "2026-04-15")

    def test_future_date_returns_zero(self):
        self._create_snapshot_with_yield(
            date(2026, 4, 15), Decimal("5000"), Decimal("100")
        )

        future = date.today() + timedelta(days=365)
        resp = self.client.get(
            f"/api/staking_yield/earned_since/?date={future.isoformat()}"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Decimal(resp.data["yield_earned"]), Decimal("0"))

    def test_user_isolation(self):
        self._create_snapshot_with_yield(
            date(2026, 4, 15), Decimal("5000"), Decimal("100")
        )

        other_user = create_random_default_user("other2")
        other_client = APIClient()
        other_client.force_authenticate(other_user)

        resp = other_client.get("/api/staking_yield/earned_since/?date=2026-04-01")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Decimal(resp.data["yield_earned"]), Decimal("0"))
