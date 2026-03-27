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
from reputation.services.rsc_supply_service import RscSupplyService

logger = logging.getLogger(__name__)

QUANTIZE_8 = Decimal("0.00000001")

# Halving schedule constants
STAKING_RELEASE_DATE = date(2026, 4, 13)
INITIAL_DAILY_EMISSION = Decimal("9500000")
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
        return (INITIAL_DAILY_EMISSION / divisor).quantize(
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
    def create_daily_snapshot(accrual_date):
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
