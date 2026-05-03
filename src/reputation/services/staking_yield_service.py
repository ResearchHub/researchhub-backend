import logging
import math
import time
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_DOWN, Decimal
from typing import Optional

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Q

from purchase.related_models.constants.rsc_exchange_currency import USD
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from reputation.distributions import create_staking_yield_distribution
from reputation.distributor import Distributor
from reputation.related_models.staking_global_snapshot import StakingGlobalSnapshot
from reputation.related_models.staking_user_snapshot import StakingUserSnapshot
from reputation.related_models.staking_yield_record import StakingYieldRecord
from reputation.services.rsc_supply_service import RscSupplyService

logger = logging.getLogger(__name__)

QUANTIZE_8 = Decimal("0.00000001")

# Halving schedule constants
STAKING_RELEASE_DATE = date(2026, 4, 11)
INITIAL_YEARLY_EMISSION = Decimal("9500000")
HALVING_PERIOD_DAYS = 64 * 365  # 64 years in days
BASE_STAKING_MULTIPLIER = Decimal("1")
STAKING_MULTIPLIER_30_DAY = Decimal("1.05")
STAKING_MULTIPLIER_180_DAY = Decimal("1.1")
STAKING_MULTIPLIER_365_DAY = Decimal("1.25")

STAKING_MULTIPLIER_TIERS = (
    (30, STAKING_MULTIPLIER_30_DAY),
    (180, STAKING_MULTIPLIER_180_DAY),
    (365, STAKING_MULTIPLIER_365_DAY),
)


def _resolve_rate_for_date(rates, target_date):
    """Return the rate from the latest record on or before `target_date`, or None."""
    chosen = None
    for record in rates:
        if record["created_date"].date() <= target_date:
            chosen = record["rate"]
        else:
            break
    return chosen


@dataclass(frozen=True)
class StakingPosition:
    stake_amount: Decimal
    multiplier: Decimal
    weighted_stake: Decimal


class StakingYieldService:
    @staticmethod
    def compute_weighted_stake(stake, multiplier):
        if stake <= 0 or multiplier <= 0:
            return Decimal("0")

        raw = stake * multiplier
        return raw.quantize(QUANTIZE_8, rounding=ROUND_DOWN)

    @staticmethod
    def compute_balance_age_multiplier(age_days):
        if age_days < 30:
            return BASE_STAKING_MULTIPLIER.quantize(QUANTIZE_8, rounding=ROUND_DOWN)

        if age_days < 180:
            return STAKING_MULTIPLIER_30_DAY.quantize(QUANTIZE_8, rounding=ROUND_DOWN)

        if age_days < 365:
            return STAKING_MULTIPLIER_180_DAY.quantize(QUANTIZE_8, rounding=ROUND_DOWN)

        return STAKING_MULTIPLIER_365_DAY.quantize(QUANTIZE_8, rounding=ROUND_DOWN)

    @staticmethod
    def compute_next_multiplier_tier(age_days):
        """Return (next_multiplier, days_until_next) for the given age.

        Returns (None, None) if the age is already at the max tier.
        """
        for threshold, multiplier in STAKING_MULTIPLIER_TIERS:
            if age_days < threshold:
                return (
                    multiplier.quantize(QUANTIZE_8, rounding=ROUND_DOWN),
                    threshold - age_days,
                )
        return (None, None)

    @staticmethod
    def get_balance_lot_details(user, reference_date):
        """Return per-lot staking multiplier details for the given user.

        Each entry includes the lot's effective start date (respecting the
        user's staking opt-in date), current age and multiplier, the next
        tier the lot will reach (if any), and the projected overall
        weighted-average multiplier across all lots on that tier transition
        date, assuming balances don't change before then.
        """
        lots = user.get_unlocked_balance_lots_lifo()
        opt_in_date = (
            user.staking_opted_in_date.date() if user.staking_opted_in_date else None
        )

        details = []
        for lot in lots:
            effective_start_date = lot.created_date
            if opt_in_date is not None:
                effective_start_date = max(effective_start_date, opt_in_date)

            age_days = max((reference_date - effective_start_date).days, 0)
            current_multiplier = StakingYieldService.compute_balance_age_multiplier(
                age_days
            )
            next_multiplier, days_until_next = (
                StakingYieldService.compute_next_multiplier_tier(age_days)
            )
            next_multiplier_date = (
                reference_date + timedelta(days=days_until_next)
                if days_until_next is not None
                else None
            )
            projected_multiplier = (
                StakingYieldService.calculate_staking_position(
                    lots, opt_in_date, next_multiplier_date
                ).multiplier
                if next_multiplier_date is not None
                else None
            )

            details.append(
                {
                    "amount": lot.amount.quantize(QUANTIZE_8, rounding=ROUND_DOWN),
                    "created_date": lot.created_date,
                    "effective_start_date": effective_start_date,
                    "age_days": age_days,
                    "current_multiplier": current_multiplier,
                    "next_multiplier": next_multiplier,
                    "days_until_next_multiplier": days_until_next,
                    "next_multiplier_date": next_multiplier_date,
                    "projected_overall_multiplier": projected_multiplier,
                }
            )

        return details

    @staticmethod
    def calculate_staking_position(lots, opt_in_date, accrual_date):
        if not lots:
            return StakingPosition(
                stake_amount=Decimal("0"),
                multiplier=Decimal("0"),
                weighted_stake=Decimal("0"),
            )

        stake_amount = Decimal("0")
        raw_weighted_stake = Decimal("0")

        for lot in lots:
            effective_start_date = lot.created_date
            if opt_in_date is not None:
                effective_start_date = max(effective_start_date, opt_in_date)

            age_days = max((accrual_date - effective_start_date).days, 0)
            lot_multiplier = StakingYieldService.compute_balance_age_multiplier(
                age_days
            )
            stake_amount += lot.amount
            raw_weighted_stake += lot.amount * lot_multiplier

        if stake_amount <= 0:
            return StakingPosition(
                stake_amount=Decimal("0"),
                multiplier=Decimal("0"),
                weighted_stake=Decimal("0"),
            )

        stake_amount = stake_amount.quantize(QUANTIZE_8, rounding=ROUND_DOWN)
        multiplier = (raw_weighted_stake / stake_amount).quantize(
            QUANTIZE_8, rounding=ROUND_DOWN
        )
        weighted_stake = StakingYieldService.compute_weighted_stake(
            stake_amount, multiplier
        )
        return StakingPosition(
            stake_amount=stake_amount,
            multiplier=multiplier,
            weighted_stake=weighted_stake,
        )

    @staticmethod
    def compute_global_staking_multiplier(total_staked, total_weighted_stake):
        if total_staked <= 0 or total_weighted_stake <= 0:
            return Decimal("0")

        return (total_weighted_stake / total_staked).quantize(
            QUANTIZE_8, rounding=ROUND_DOWN
        )

    @staticmethod
    def compute_apy_for_snapshot(snapshot: StakingGlobalSnapshot) -> float:
        """APY % implied by the daily emission for a snapshot's accrual_date."""
        if snapshot.total_staked <= 0:
            return 0.0

        daily_emission = StakingYieldService.compute_total_daily_emission(
            snapshot.accrual_date
        )
        if daily_emission <= 0:
            return 0.0

        return float(daily_emission) / float(snapshot.total_staked) * 365 * 100

    @staticmethod
    def holders_count(snapshot: StakingGlobalSnapshot) -> int:
        return snapshot.user_snapshots.filter(stake_amount__gt=0).count()

    @staticmethod
    def build_history(start_date: Optional[date], end_date: Optional[date]) -> list:
        """Return per-snapshot history rows in ascending date order.

        Each row: {accrual_date, apy, total_staked_rsc, total_value_locked_usd,
        holders}. `total_value_locked_usd` is `None` when no USD rate exists on
        or before the snapshot date.
        """
        snapshots_qs = StakingGlobalSnapshot.objects.all()
        if start_date is not None:
            snapshots_qs = snapshots_qs.filter(accrual_date__gte=start_date)
        if end_date is not None:
            snapshots_qs = snapshots_qs.filter(accrual_date__lte=end_date)

        snapshots = list(
            snapshots_qs.annotate(
                holders=Count(
                    "user_snapshots",
                    filter=Q(user_snapshots__stake_amount__gt=0),
                )
            ).order_by("accrual_date")
        )
        if not snapshots:
            return []

        rate_lookup_end = snapshots[-1].accrual_date
        rates = list(
            RscExchangeRate.objects.filter(
                target_currency=USD,
                created_date__date__lte=rate_lookup_end,
            )
            .order_by("created_date")
            .values("created_date", "rate")
        )

        rows = []
        for snapshot in snapshots:
            rate = _resolve_rate_for_date(rates, snapshot.accrual_date)
            if rate is None:
                tvl_usd = None
            else:
                tvl_usd = snapshot.total_staked * Decimal(str(rate))

            rows.append(
                {
                    "accrual_date": snapshot.accrual_date,
                    "apy": StakingYieldService.compute_apy_for_snapshot(snapshot),
                    "total_staked_rsc": snapshot.total_staked,
                    "total_value_locked_usd": tvl_usd,
                    "holders": snapshot.holders,
                }
            )
        return rows

    @staticmethod
    def compute_total_daily_emission(accrual_date):
        """Compute total daily emission using the halving formula.

        daily_emission = 9500000 / (2 ^ (days_since_release / (64 * 365)))

        Returns Decimal("0") for dates before the release date.
        """
        if accrual_date is None:
            accrual_date = date.today()

        days_since_release = (accrual_date - STAKING_RELEASE_DATE).days
        if days_since_release < 0:
            return Decimal("0")

        exponent = days_since_release / HALVING_PERIOD_DAYS
        divisor = Decimal(str(math.pow(2, exponent)))
        return ((INITIAL_YEARLY_EMISSION / Decimal("365")) / divisor).quantize(
            QUANTIZE_8, rounding=ROUND_DOWN
        )

    @staticmethod
    def compute_daily_yield_from_pool_share(
        weighted_stake,
        total_weighted_stake,
        accrual_date=None,
    ):
        """Compute quantized daily yield from the user's share of daily emission."""
        if weighted_stake <= 0 or total_weighted_stake <= 0:
            return Decimal("0")

        daily_emission = StakingYieldService.compute_total_daily_emission(accrual_date)
        if daily_emission <= 0:
            return Decimal("0")

        raw = daily_emission * (weighted_stake / total_weighted_stake)
        return raw.quantize(QUANTIZE_8, rounding=ROUND_DOWN)

    @staticmethod
    def create_yield_distribution(user, accrual):
        """Create a locked STAKING_YIELD distribution for the given accrual.

        Returns the Distribution record, or None if yield is zero.
        """
        if accrual.yield_amount <= 0:
            return None

        distribution = create_staking_yield_distribution(accrual.yield_amount)
        distributor = Distributor(
            distribution,
            user,
            accrual,
            time.time(),
        )
        record = distributor.distribute_locked_balance()
        return record

    @staticmethod
    def create_daily_snapshots(accrual_date):
        """Create a StakingGlobalSnapshot with circulating supply and user stakes.

        Returns the created StakingGlobalSnapshot, or None if a snapshot
        already exists for the given accrual_date.

        Raises on any failure (supply fetch, DB errors, etc.) so callers
        can retry.
        """
        User = get_user_model()

        if accrual_date < STAKING_RELEASE_DATE:
            logger.info(
                "Skipping staking snapshot creation for pre-release accrual_date=%s",
                accrual_date,
            )
            return None

        existing = StakingGlobalSnapshot.load_for_accrual_date(accrual_date)
        if existing is not None:
            logger.info(
                "Staking snapshot already exists for %s, skipping create",
                accrual_date,
            )
            return existing

        supply = RscSupplyService.fetch_circulating_supply()

        eligible_users = User.objects.filter(
            is_staking_opted_in=True,
            is_active=True,
            is_suspended=False,
            probable_spammer=False,
        ).iterator()

        total_staked = Decimal("0")
        total_weighted_stake = Decimal("0")
        position_rows = []

        for user in eligible_users:
            user_lots = user.get_unlocked_balance_lots_lifo()
            user_opt_in_date = (
                user.staking_opted_in_date.date()
                if user.staking_opted_in_date
                else None
            )
            staking_position = StakingYieldService.calculate_staking_position(
                user_lots, user_opt_in_date, accrual_date
            )
            if (
                staking_position.stake_amount <= 0
                or staking_position.weighted_stake <= 0
            ):
                continue

            total_staked += staking_position.stake_amount
            total_weighted_stake += staking_position.weighted_stake
            position_rows.append(
                StakingUserSnapshot(
                    user=user,
                    stake_amount=staking_position.stake_amount,
                    multiplier=staking_position.multiplier,
                    weighted_stake=staking_position.weighted_stake,
                )
            )

        global_multiplier = StakingYieldService.compute_global_staking_multiplier(
            total_staked, total_weighted_stake
        )

        with transaction.atomic():
            global_snapshot = StakingGlobalSnapshot.objects.create(
                accrual_date=accrual_date,
                circulating_supply=supply,
                total_staked=total_staked,
                total_weighted_stake=total_weighted_stake,
            )
            for position_row in position_rows:
                position_row.global_snapshot = global_snapshot
            StakingUserSnapshot.objects.bulk_create(position_rows)

        logger.info(
            "Created daily StakingGlobalSnapshot pk=%d accrual_date=%s supply=%s "
            "total_staked=%s total_weighted_stake=%s global_multiplier=%s",
            global_snapshot.pk,
            accrual_date,
            supply,
            total_staked,
            total_weighted_stake,
            global_multiplier,
        )
        return global_snapshot

    @staticmethod
    def distribute_yield(accrual_date):
        """Distribute staking yield for the given accrual date.

        Returns the number of users who received a distribution, or None
        if no snapshot exists for the date.

        Raises on any failure so callers can retry.
        """
        if accrual_date < STAKING_RELEASE_DATE:
            logger.info(
                "Skipping staking yield distribution for pre-release accrual_date=%s",
                accrual_date,
            )
            return None

        global_snapshot = StakingGlobalSnapshot.load_for_accrual_date(accrual_date)
        if global_snapshot is None:
            logger.info(
                "No staking snapshot found for %s, skipping distribution",
                accrual_date,
            )
            return None

        distributed_count = 0
        user_snapshots = global_snapshot.user_snapshots.select_related(
            "user"
        ).iterator()
        for user_snapshot in user_snapshots:
            user = user_snapshot.user
            if not user.is_active or user.is_suspended or user.probable_spammer:
                continue

            daily_yield = StakingYieldService.compute_daily_yield_from_pool_share(
                user_snapshot.weighted_stake,
                global_snapshot.total_weighted_stake,
                accrual_date,
            )

            with transaction.atomic():
                (
                    yield_record,
                    _,
                ) = StakingYieldRecord.objects.select_for_update().get_or_create(
                    user_snapshot=user_snapshot,
                    defaults={
                        "yield_amount": daily_yield,
                    },
                )

                if yield_record.distribution_id is not None:
                    continue  # already paid

                yield_record.yield_amount = daily_yield

                if daily_yield <= 0:
                    yield_record.save()
                    continue

                record = StakingYieldService.create_yield_distribution(
                    user, yield_record
                )
                if record:
                    yield_record.distribution = record

                yield_record.save()
                if record:
                    distributed_count += 1

        logger.info(
            "Staking yield distribution complete for %s: %d users paid",
            accrual_date,
            distributed_count,
        )
        return distributed_count
