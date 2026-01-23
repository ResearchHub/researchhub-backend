import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from django.db import transaction
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from purchase.models import (
    BalanceEntryDate,
    FundingCredit,
    StakingDistributionRecord,
    StakingSnapshot,
)
from purchase.related_models.constants.staking import (
    MINIMUM_STAKING_BALANCE,
    STAKING_MULTIPLIER_TIERS,
    STAKING_TIER_NAMES,
    WEEKLY_STAKING_POOL,
)
from user.models import User

logger = logging.getLogger(__name__)


class StakingService:
    """
    Service for managing staking rewards and funding credit distributions.

    The staking system rewards RSC holders with non-liquid funding credits
    based on their holding duration. Users who hold RSC longer earn
    proportionally higher rewards through time-weighted multipliers.
    """

    def get_multiplier_for_days(self, days_held: int) -> Decimal:
        """
        Returns the multiplier based on holding duration.

        Args:
            days_held: Number of days RSC has been held

        Returns:
            Multiplier value (1.0x to 7.5x)
        """
        for min_days, max_days, multiplier in STAKING_MULTIPLIER_TIERS:
            if max_days is None:
                # Last tier (365+ days)
                if days_held >= min_days:
                    return multiplier
            elif min_days <= days_held < max_days:
                return multiplier

        # Default to lowest tier
        return Decimal("1.0")

    def get_tier_name(self, multiplier: Decimal) -> str:
        """Returns the tier name for a given multiplier."""
        return STAKING_TIER_NAMES.get(multiplier, "Unknown")

    def get_days_until_next_tier(self, days_held: int) -> Optional[int]:
        """
        Returns the number of days until the next multiplier tier.

        Args:
            days_held: Current number of days held

        Returns:
            Days until next tier, or None if at max tier
        """
        # Find the current tier and the next tier
        for i, (min_days, max_days, _) in enumerate(STAKING_MULTIPLIER_TIERS):
            if max_days is None:
                # This is the last tier
                if days_held >= min_days:
                    return None
            elif min_days <= days_held < max_days:
                # Found current tier, return days until next tier's min_days
                return max_days - days_held

        return None

    def calculate_user_weighted_balance(
        self, user: User, as_of_date: date
    ) -> tuple[Decimal, Decimal, Decimal]:
        """
        Calculate a user's total RSC balance and weighted balance using
        FIFO entry dates for multiplier calculation.

        Args:
            user: The user to calculate for
            as_of_date: The date to calculate as of

        Returns:
            Tuple of (rsc_balance, effective_multiplier, weighted_balance)
        """
        # Get all balance entry dates with remaining amounts
        entry_dates = BalanceEntryDate.objects.filter(
            user=user,
            remaining_amount__gt=0,
        ).order_by("entry_date")

        if not entry_dates.exists():
            return Decimal("0"), Decimal("1.0"), Decimal("0")

        total_balance = Decimal("0")
        total_weighted = Decimal("0")

        for entry in entry_dates:
            days_held = (as_of_date - entry.entry_date.date()).days
            multiplier = self.get_multiplier_for_days(days_held)

            total_balance += entry.remaining_amount
            total_weighted += entry.remaining_amount * multiplier

        # Calculate effective multiplier as weighted average
        effective_multiplier = (
            total_weighted / total_balance if total_balance > 0 else Decimal("1.0")
        )

        return total_balance, effective_multiplier, total_weighted

    def create_daily_snapshot(
        self, user: User, snapshot_date: date
    ) -> Optional[StakingSnapshot]:
        """
        Creates a daily snapshot of a user's staking position.

        Args:
            user: The user to create snapshot for
            snapshot_date: The date of the snapshot

        Returns:
            Created StakingSnapshot or None if user doesn't qualify
        """
        rsc_balance, multiplier, weighted_balance = self.calculate_user_weighted_balance(
            user, snapshot_date
        )

        # Skip users below minimum balance
        if rsc_balance < MINIMUM_STAKING_BALANCE:
            return None

        snapshot, created = StakingSnapshot.objects.update_or_create(
            user=user,
            snapshot_date=snapshot_date,
            defaults={
                "rsc_balance": rsc_balance,
                "multiplier": multiplier,
                "weighted_balance": weighted_balance,
            },
        )

        return snapshot

    def create_all_user_snapshots(self, snapshot_date: date) -> int:
        """
        Batch creates snapshots for all eligible users.

        Args:
            snapshot_date: The date of the snapshot

        Returns:
            Number of snapshots created
        """
        # Get users with balance entry dates
        users_with_balance = (
            BalanceEntryDate.objects.filter(remaining_amount__gt=0)
            .values_list("user_id", flat=True)
            .distinct()
        )

        count = 0
        for user_id in users_with_balance:
            try:
                user = User.objects.get(id=user_id)
                snapshot = self.create_daily_snapshot(user, snapshot_date)
                if snapshot:
                    count += 1
            except User.DoesNotExist:
                logger.warning(f"User {user_id} not found during snapshot creation")
            except Exception as e:
                logger.error(f"Error creating snapshot for user {user_id}: {e}")

        logger.info(f"Created {count} staking snapshots for {snapshot_date}")
        return count

    def distribute_weekly_rewards(
        self, distribution_date: date
    ) -> StakingDistributionRecord:
        """
        Distributes weekly staking rewards as funding credits to all stakers
        based on their weighted RSC holdings.

        Args:
            distribution_date: The date of the distribution

        Returns:
            StakingDistributionRecord with distribution details
        """
        # Check if already distributed
        existing = StakingDistributionRecord.objects.filter(
            distribution_date=distribution_date,
            status=StakingDistributionRecord.Status.COMPLETED,
        ).first()
        if existing:
            logger.warning(f"Distribution already completed for {distribution_date}")
            return existing

        # Get the most recent snapshot date (use yesterday's snapshots)
        snapshot_date = distribution_date - timedelta(days=1)

        # Get all snapshots for the snapshot date
        snapshots = StakingSnapshot.objects.filter(snapshot_date=snapshot_date)

        # Calculate total weighted balance
        total_weighted = snapshots.aggregate(
            total=Coalesce(Sum("weighted_balance"), Decimal("0"))
        )["total"]

        # Create distribution record
        record = StakingDistributionRecord.objects.create(
            distribution_date=distribution_date,
            total_pool_amount=WEEKLY_STAKING_POOL,
            total_weighted_balance=total_weighted,
            users_rewarded=0,
            status=StakingDistributionRecord.Status.PENDING,
        )

        if total_weighted <= 0:
            record.status = StakingDistributionRecord.Status.COMPLETED
            record.save()
            logger.info(f"No stakers to distribute to for {distribution_date}")
            return record

        try:
            users_rewarded = 0

            with transaction.atomic():
                for snapshot in snapshots.iterator():
                    # Calculate user's share
                    user_share = (
                        snapshot.weighted_balance / total_weighted
                    ) * WEEKLY_STAKING_POOL

                    if user_share <= 0:
                        continue

                    # Create funding credit record
                    FundingCredit.objects.create(
                        user=snapshot.user,
                        amount=user_share,
                        credit_type=FundingCredit.CreditType.STAKING_REWARD,
                        content_type=None,
                        object_id=None,
                    )

                    users_rewarded += 1

                record.users_rewarded = users_rewarded
                record.status = StakingDistributionRecord.Status.COMPLETED
                record.save()

            logger.info(
                f"Distributed {WEEKLY_STAKING_POOL} credits to {users_rewarded} users"
            )

        except Exception as e:
            record.status = StakingDistributionRecord.Status.FAILED
            record.error_message = str(e)
            record.save()
            logger.error(f"Distribution failed for {distribution_date}: {e}")
            raise

        return record

    def get_user_staking_info(self, user: User) -> dict:
        """
        Returns current staking info for a user.

        Args:
            user: The user to get info for

        Returns:
            Dict with staking information
        """
        today = timezone.now().date()
        rsc_balance, multiplier, weighted_balance = self.calculate_user_weighted_balance(
            user, today
        )

        # Get the oldest entry date to determine days held
        oldest_entry = (
            BalanceEntryDate.objects.filter(user=user, remaining_amount__gt=0)
            .order_by("entry_date")
            .first()
        )

        days_held = 0
        if oldest_entry:
            days_held = (today - oldest_entry.entry_date.date()).days

        days_until_next = self.get_days_until_next_tier(days_held)

        # Calculate projected weekly credits
        # This is an estimate based on current pool and participation
        latest_distribution = StakingDistributionRecord.objects.filter(
            status=StakingDistributionRecord.Status.COMPLETED
        ).order_by("-distribution_date").first()

        if latest_distribution and latest_distribution.total_weighted_balance > 0:
            projected_share = weighted_balance / latest_distribution.total_weighted_balance
            projected_weekly = projected_share * WEEKLY_STAKING_POOL
        else:
            # Assume user is only staker for estimate
            projected_weekly = WEEKLY_STAKING_POOL if rsc_balance > 0 else Decimal("0")

        # Calculate projected APY
        # APY = (weekly_credits * 52) / rsc_balance * 100
        if rsc_balance > 0:
            annual_credits = projected_weekly * 52
            projected_apy = (annual_credits / rsc_balance) * 100
        else:
            projected_apy = Decimal("0")

        return {
            "rsc_balance": rsc_balance,
            "weighted_balance": weighted_balance,
            "current_multiplier": multiplier,
            "multiplier_tier": self.get_tier_name(
                self.get_multiplier_for_days(days_held)
            ),
            "days_held": days_held,
            "days_until_next_tier": days_until_next,
            "projected_weekly_credits": projected_weekly,
            "projected_apy": projected_apy,
        }

    def handle_withdrawal_fifo(self, user: User, amount: Decimal) -> None:
        """
        Updates BalanceEntryDate records using FIFO when user withdraws RSC.
        Newest RSC is withdrawn first to preserve higher multipliers on older holdings.

        Args:
            user: The user withdrawing
            amount: Amount being withdrawn
        """
        remaining_to_withdraw = amount

        # Get entries ordered by newest first (FIFO means newest withdrawn first)
        entries = BalanceEntryDate.objects.filter(
            user=user,
            remaining_amount__gt=0,
        ).order_by("-entry_date")  # Newest first

        with transaction.atomic():
            for entry in entries:
                if remaining_to_withdraw <= 0:
                    break

                if entry.remaining_amount <= remaining_to_withdraw:
                    # Use entire entry
                    remaining_to_withdraw -= entry.remaining_amount
                    entry.remaining_amount = Decimal("0")
                else:
                    # Partial use of entry
                    entry.remaining_amount -= remaining_to_withdraw
                    remaining_to_withdraw = Decimal("0")

                entry.save()

        if remaining_to_withdraw > 0:
            logger.warning(
                f"User {user.id} withdrew {amount} but only had "
                f"{amount - remaining_to_withdraw} in balance entry dates"
            )
