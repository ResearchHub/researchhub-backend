from datetime import date, datetime, timedelta, timezone, time
from decimal import Decimal
from unittest.mock import patch

from django.core.cache import cache
from rest_framework.test import APIClient, APITestCase

from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from django.contrib.contenttypes.models import ContentType

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


class StakingPublicStatsTestBase(APITestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()

    def tearDown(self):
        cache.clear()

    def _create_global_snapshot(
        self,
        accrual_date,
        total_staked=Decimal("0"),
        circulating_supply=Decimal("215052673"),
        weighted_stake=None,
    ):
        return StakingGlobalSnapshot.objects.create(
            accrual_date=accrual_date,
            circulating_supply=circulating_supply,
            total_staked=total_staked,
            total_weighted_stake=(
                total_staked if weighted_stake is None else weighted_stake
            ),
        )

    def _add_user_snapshot(self, snapshot, stake, label=""):
        user = create_random_default_user(f"staker_{label or stake}")
        return StakingUserSnapshot.objects.create(
            global_snapshot=snapshot,
            user=user,
            stake_amount=Decimal(stake),
            multiplier=Decimal("1"),
            weighted_stake=Decimal(stake),
        )

    def _create_usd_rate(self, rate, on_date):
        record = RscExchangeRate.objects.create(
            rate=float(rate),
            real_rate=float(rate),
            price_source="COIN_GECKO",
            target_currency="USD",
        )
        # `created_date` is auto-set to now; force it to the desired day so the
        # /history endpoint resolves the rate correctly.
        forced_dt = datetime.combine(on_date, datetime.min.time(), tzinfo=timezone.utc)
        RscExchangeRate.objects.filter(pk=record.pk).update(created_date=forced_dt)
        cache.delete(RscExchangeRate._LATEST_EXCHANGE_RATE_CACHE_KEY)
        return record


class StakingStatsEndpointTest(StakingPublicStatsTestBase):
    def test_public_access(self):
        # No auth required.
        resp = self.client.get("/api/staking_yield/stats/")
        self.assertEqual(resp.status_code, 200)

    def test_empty_state_returns_zeroes(self):
        resp = self.client.get("/api/staking_yield/stats/")
        self.assertEqual(resp.status_code, 200)
        data = resp.data
        self.assertIsNone(data["accrual_date"])
        self.assertEqual(float(data["apy"]), 0.0)
        self.assertEqual(float(data["apy_30d_avg"]), 0.0)
        self.assertEqual(int(data["holders"]), 0)
        self.assertEqual(float(data["top_10_concentration_pct"]), 0.0)
        self.assertEqual(Decimal(data["total_staked_rsc"]), Decimal("0"))
        self.assertIsNone(data["total_value_locked_usd"])
        self.assertEqual(float(data["pct_of_supply_staked"]), 0.0)

    def test_single_user_top_10_is_100_pct(self):
        snap = self._create_global_snapshot(
            date(2026, 4, 15), total_staked=Decimal("1000")
        )
        self._add_user_snapshot(snap, Decimal("1000"), label="solo")

        resp = self.client.get("/api/staking_yield/stats/")
        data = resp.data
        self.assertEqual(data["accrual_date"], "2026-04-15")
        self.assertEqual(int(data["holders"]), 1)
        self.assertAlmostEqual(float(data["top_10_concentration_pct"]), 100.0, places=2)

    def test_top_10_pct_with_ten_uniform_stakers(self):
        snap = self._create_global_snapshot(
            date(2026, 4, 20), total_staked=Decimal("1000")
        )
        for i in range(10):
            self._add_user_snapshot(snap, Decimal("100"), label=f"u{i}")

        resp = self.client.get("/api/staking_yield/stats/")
        data = resp.data
        self.assertEqual(int(data["holders"]), 10)
        # Top 10% of 10 = 1 staker with 100 of 1000 = 10%
        self.assertAlmostEqual(float(data["top_10_concentration_pct"]), 10.0, places=2)

    def test_top_10_pct_with_skewed_distribution(self):
        snap = self._create_global_snapshot(
            date(2026, 4, 20), total_staked=Decimal("550")
        )
        # 10 stakers, top one has 100, rest have 50 each
        self._add_user_snapshot(snap, Decimal("100"), label="whale")
        for i in range(9):
            self._add_user_snapshot(snap, Decimal("50"), label=f"u{i}")

        resp = self.client.get("/api/staking_yield/stats/")
        # Top 10% of 10 = 1 staker; whale holds 100 / 550 ≈ 18.18%
        self.assertAlmostEqual(
            float(resp.data["top_10_concentration_pct"]),
            100.0 / 550.0 * 100,
            places=2,
        )

    def test_top_10_pct_ceil_rounding(self):
        snap = self._create_global_snapshot(
            date(2026, 4, 20), total_staked=Decimal("700")
        )
        # 7 uniform stakers; top 10% rounds up to 1 (ceil(0.7) = 1).
        for i in range(7):
            self._add_user_snapshot(snap, Decimal("100"), label=f"u{i}")

        resp = self.client.get("/api/staking_yield/stats/")
        # 1 of 7 stakers, each with 100 of 700 = ~14.29%
        self.assertAlmostEqual(
            float(resp.data["top_10_concentration_pct"]),
            100.0 / 700.0 * 100,
            places=2,
        )

    def test_apy_30d_avg_over_multiple_snapshots(self):
        # Three snapshots with different total_staked → different APYs.
        # Average should be the mean of the three APY values.
        for i, (d, stake) in enumerate(
            [
                (date(2026, 4, 15), Decimal("1000000")),
                (date(2026, 4, 16), Decimal("2000000")),
                (date(2026, 4, 17), Decimal("4000000")),
            ]
        ):
            snap = self._create_global_snapshot(d, total_staked=stake)
            self._add_user_snapshot(snap, stake, label=f"a{i}")

        snapshots = list(StakingGlobalSnapshot.objects.order_by("-accrual_date")[:30])
        expected_avg = sum(
            StakingYieldService.compute_apy_for_snapshot(s) for s in snapshots
        ) / len(snapshots)

        resp = self.client.get("/api/staking_yield/stats/")
        self.assertAlmostEqual(float(resp.data["apy_30d_avg"]), expected_avg, places=4)

    def test_tvl_uses_latest_usd_rate(self):
        snap = self._create_global_snapshot(
            date(2026, 4, 20), total_staked=Decimal("1000")
        )
        self._add_user_snapshot(snap, Decimal("1000"), label="solo")
        self._create_usd_rate(Decimal("0.50"), on_date=date(2026, 4, 20))

        resp = self.client.get("/api/staking_yield/stats/")
        # 1000 RSC * $0.50 = $500.00
        self.assertEqual(
            Decimal(resp.data["total_value_locked_usd"]), Decimal("500.00")
        )


class StakingHistoryEndpointTest(StakingPublicStatsTestBase):
    def test_public_access(self):
        resp = self.client.get("/api/staking_yield/history/")
        self.assertEqual(resp.status_code, 200)

    def test_invalid_range_returns_400(self):
        resp = self.client.get("/api/staking_yield/history/?range=junk")
        self.assertEqual(resp.status_code, 400)

    def test_empty_state_returns_empty_results(self):
        resp = self.client.get("/api/staking_yield/history/?range=all")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["range"], "all")
        self.assertEqual(resp.data["results"], [])

    def test_results_ascending_by_date(self):
        for d in [date(2026, 4, 17), date(2026, 4, 15), date(2026, 4, 16)]:
            snap = self._create_global_snapshot(d, total_staked=Decimal("1000"))
            self._add_user_snapshot(snap, Decimal("1000"), label=str(d))

        resp = self.client.get("/api/staking_yield/history/?range=all")
        dates = [row["accrual_date"] for row in resp.data["results"]]
        self.assertEqual(dates, ["2026-04-15", "2026-04-16", "2026-04-17"])

    def test_range_filter_applies_window(self):
        today = date.today()
        old = today - timedelta(days=100)
        recent = today - timedelta(days=3)

        for d in [old, recent]:
            snap = self._create_global_snapshot(d, total_staked=Decimal("1000"))
            self._add_user_snapshot(snap, Decimal("1000"), label=str(d))

        resp = self.client.get("/api/staking_yield/history/?range=7d")
        dates = [row["accrual_date"] for row in resp.data["results"]]
        self.assertEqual(dates, [recent.isoformat()])

    def test_default_range_is_90d(self):
        today = date.today()
        snap = self._create_global_snapshot(
            today - timedelta(days=2), total_staked=Decimal("1000")
        )
        self._add_user_snapshot(snap, Decimal("1000"), label="recent")

        resp = self.client.get("/api/staking_yield/history/")
        self.assertEqual(resp.data["range"], "90d")
        self.assertEqual(len(resp.data["results"]), 1)

    def test_per_day_usd_pricing(self):
        d1 = date(2026, 4, 15)
        d2 = date(2026, 4, 16)
        snap1 = self._create_global_snapshot(d1, total_staked=Decimal("1000"))
        self._add_user_snapshot(snap1, Decimal("1000"), label="a")
        snap2 = self._create_global_snapshot(d2, total_staked=Decimal("1000"))
        self._add_user_snapshot(snap2, Decimal("1000"), label="b")

        self._create_usd_rate(Decimal("0.40"), on_date=d1)
        self._create_usd_rate(Decimal("0.60"), on_date=d2)

        resp = self.client.get("/api/staking_yield/history/?range=all")
        rows = {row["accrual_date"]: row for row in resp.data["results"]}
        self.assertEqual(
            Decimal(rows["2026-04-15"]["total_value_locked_usd"]), Decimal("400.00")
        )
        self.assertEqual(
            Decimal(rows["2026-04-16"]["total_value_locked_usd"]), Decimal("600.00")
        )

    def test_tvl_null_when_no_rate_exists(self):
        snap = self._create_global_snapshot(
            date(2026, 4, 15), total_staked=Decimal("1000")
        )
        self._add_user_snapshot(snap, Decimal("1000"), label="solo")

        resp = self.client.get("/api/staking_yield/history/?range=all")
        self.assertIsNone(resp.data["results"][0]["total_value_locked_usd"])

    def test_unknown_query_params_dont_bust_cache(self):
        snap = self._create_global_snapshot(
            date(2026, 4, 15), total_staked=Decimal("1000")
        )
        self._add_user_snapshot(snap, Decimal("1000"), label="solo")

        # Prime the cache with a vanilla request.
        first = self.client.get("/api/staking_yield/history/?range=all")
        self.assertEqual(first.status_code, 200)

        # An attacker varying the URL with junk params must not trigger another
        # DB-backed build_history call. Mutating snapshot data after the cache
        # is primed proves the second response came from cache.
        StakingGlobalSnapshot.objects.filter(pk=snap.pk).update(
            total_staked=Decimal("99999999")
        )

        nonced = self.client.get(
            "/api/staking_yield/history/?range=all&nonce=attack&foo=bar"
        )
        self.assertEqual(nonced.status_code, 200)
        self.assertEqual(nonced.data, first.data)

    def test_holders_per_day(self):
        snap1 = self._create_global_snapshot(
            date(2026, 4, 15), total_staked=Decimal("100")
        )
        self._add_user_snapshot(snap1, Decimal("100"), label="d1u1")

        snap2 = self._create_global_snapshot(
            date(2026, 4, 16), total_staked=Decimal("300")
        )
        self._add_user_snapshot(snap2, Decimal("100"), label="d2u1")
        self._add_user_snapshot(snap2, Decimal("200"), label="d2u2")
        # zero-stake snapshot row should not count as a holder
        self._add_user_snapshot(snap2, Decimal("0"), label="d2u3")

        resp = self.client.get("/api/staking_yield/history/?range=all")
        rows = {row["accrual_date"]: row for row in resp.data["results"]}
        self.assertEqual(int(rows["2026-04-15"]["holders"]), 1)
        self.assertEqual(int(rows["2026-04-16"]["holders"]), 2)
