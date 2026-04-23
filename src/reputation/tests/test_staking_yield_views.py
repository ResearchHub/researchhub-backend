from datetime import date, timedelta
from decimal import Decimal

from rest_framework.test import APIClient, APITestCase

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
