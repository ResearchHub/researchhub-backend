import calendar
import math
import time
from datetime import date
from decimal import ROUND_DOWN, Decimal

from reputation.distributions import create_staking_yield_distribution
from reputation.distributor import Distributor

QUANTIZE_8 = Decimal("0.00000001")

# Halving schedule constants
STAKING_RELEASE_DATE = date(2026, 4, 13)
INITIAL_DAILY_EMISSION = Decimal("9500000")
HALVING_PERIOD_DAYS = 64 * 365  # 64 years in days


def days_in_year(year=None):
    if year is None:
        year = date.today().year
    return 365 + calendar.isleap(year)


class StakingYieldService:
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
