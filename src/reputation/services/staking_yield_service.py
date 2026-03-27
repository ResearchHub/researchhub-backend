import calendar
import math
import time
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_DOWN, Decimal

from reputation.distributions import create_staking_yield_distribution
from reputation.distributor import Distributor

QUANTIZE_8 = Decimal("0.00000001")
HUNDRED = Decimal("100")

# Halving schedule constants
STAKING_RELEASE_DATE = date(2026, 4, 13)
INITIAL_DAILY_EMISSION = Decimal("9500000")
HALVING_PERIOD_DAYS = 64 * 365  # 64 years in days


def days_in_year(year=None):
    if year is None:
        year = date.today().year
    return 365 + calendar.isleap(year)


class StakingYieldService:
    @staticmethod
    def compute_annualized_rate(stake, multiplier, snapshot):
        """Compute the annualized yield rate for a single user.

        Uses the halving-based daily emission for the snapshot's accrual_date,
        then annualizes: rate = 100 * daily_emission * days_in_year * multiplier / total_weighted_stake

        Returns Decimal annualized rate (e.g. 10.5 means 10.5%).
        Returns Decimal("0") when denominator is zero or negative.
        """
        if stake <= 0 or multiplier <= 0:
            return Decimal("0")

        if snapshot.total_weighted_stake <= 0:
            return Decimal("0")

        daily_emission = StakingYieldService.compute_total_daily_emission(
            snapshot.accrual_date
        )
        year = snapshot.accrual_date.year if snapshot.accrual_date else None
        emission_per_year = daily_emission * Decimal(str(days_in_year(year)))

        return HUNDRED * emission_per_year * multiplier / snapshot.total_weighted_stake

    @staticmethod
    def compute_weighted_stake(stake, multiplier):
        if stake <= 0 or multiplier <= 0:
            return Decimal("0")

        raw = stake * multiplier
        return raw.quantize(QUANTIZE_8, rounding=ROUND_DOWN)

    @staticmethod
    def compute_proration(staking_opted_in_date, accrual_date):
        """Compute the fraction of the accrual day the user was eligible.

        If the user opted in before the accrual day, returns 1.
        If the user opted in during the accrual day, returns the fraction
        of the day remaining after the opt-in time.
        If the user opted in after the accrual day, returns 0.
        """
        if staking_opted_in_date is None:
            return Decimal("1")

        # Ensure we work in UTC
        if staking_opted_in_date.tzinfo is not None:
            opted_in_utc = staking_opted_in_date.astimezone(timezone.utc)
        else:
            opted_in_utc = staking_opted_in_date.replace(tzinfo=timezone.utc)

        accrual_start = datetime(
            accrual_date.year, accrual_date.month, accrual_date.day, tzinfo=timezone.utc
        )
        accrual_end = accrual_start + timedelta(days=1)

        if opted_in_utc <= accrual_start:
            return Decimal("1")

        if opted_in_utc >= accrual_end:
            return Decimal("0")

        remaining_seconds = (accrual_end - opted_in_utc).total_seconds()
        total_seconds = Decimal("86400")
        fraction = Decimal(str(remaining_seconds)) / total_seconds
        return fraction.quantize(QUANTIZE_8, rounding=ROUND_DOWN)

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
        proration,
        accrual_date=None,
    ):
        """Compute quantized daily yield from the user's share of daily emission."""
        if weighted_stake <= 0 or total_weighted_stake <= 0 or proration <= 0:
            return Decimal("0")

        daily_emission = StakingYieldService.compute_total_daily_emission(accrual_date)
        if daily_emission <= 0:
            return Decimal("0")

        raw = daily_emission * (weighted_stake / total_weighted_stake) * proration
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
