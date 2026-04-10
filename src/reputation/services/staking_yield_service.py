import logging
import math
import time
from datetime import date
from decimal import ROUND_DOWN, Decimal

from django.contrib.auth import get_user_model
from django.db import transaction

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


class StakingYieldService:
    @staticmethod
    def compute_weighted_stake(stake, multiplier):
        if stake <= 0 or multiplier <= 0:
            return Decimal("0")

        raw = stake * multiplier
        return raw.quantize(QUANTIZE_8, rounding=ROUND_DOWN)

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
            stake = user.get_available_balance()
            if stake is None:
                continue

            stake = Decimal(str(stake))
            if stake <= 0:
                continue

            multiplier = Decimal("1")  # v1: hardcoded
            weighted_stake = StakingYieldService.compute_weighted_stake(
                stake, multiplier
            )
            if weighted_stake <= 0:
                continue

            total_staked += stake
            total_weighted_stake += weighted_stake
            position_rows.append(
                StakingUserSnapshot(
                    user=user,
                    stake_amount=stake,
                    multiplier=multiplier,
                    weighted_stake=weighted_stake,
                )
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
            "total_staked=%s total_weighted_stake=%s",
            global_snapshot.pk,
            accrual_date,
            supply,
            total_staked,
            total_weighted_stake,
        )
        return global_snapshot

    @staticmethod
    def distribute_yield(accrual_date):
        """Distribute staking yield for the given accrual date.

        Returns the number of users who received a distribution, or None
        if no snapshot exists for the date.

        Raises on any failure so callers can retry.
        """
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
