import logging
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from analytics.tasks import track_revenue_event
from purchase.models import Balance, FundingPool, Grant, Purchase, RscExchangeRate
from purchase.related_models.constants import (
    MAXIMUM_FUNDRAISE_CONTRIBUTION_AMOUNT_RSC,
    MINIMUM_FUNDRAISE_CONTRIBUTION_AMOUNT_RSC,
)
from purchase.related_models.constants.currency import RSC
from purchase.services.fundraise_service import FundraiseService
from reputation.models import BountyFee
from reputation.utils import calculate_bounty_fees, deduct_bounty_fees
from user.models import User

logger = logging.getLogger(__name__)


class FundingPoolService:
    """Service for FundingPool contributions and pool lifecycle helpers."""

    def create_pool_for_grant(self, grant: Grant) -> FundingPool:
        """Create the community contribution pot for a grant (one pool per grant)."""
        pool, _created = FundingPool.objects.get_or_create(
            grant=grant,
            defaults={"created_by": grant.created_by},
        )
        return pool

    def validate_pool_for_contribution(
        self, pool: FundingPool
    ) -> tuple[bool, str | None]:
        """Validate that a funding pool can accept contributions."""
        if pool.status != FundingPool.OPEN:
            return False, "Funding pool is not open"
        return True, None

    def create_contribution(
        self,
        user: User,
        pool: FundingPool,
        amount: Decimal,
        currency: str = RSC,
        use_credits: bool = True,
    ) -> tuple[Purchase | None, str | None]:
        """
        Validate and create an RSC contribution to a funding pool.


        Fees and balance debits follow the fundraise pattern;
        net amount is credited to ``pool.amount_holding``.
        """
        is_valid, error = self.validate_pool_for_contribution(pool)
        if not is_valid:
            return None, error

        if currency != RSC:
            return None, "Only RSC contributions are supported for funding pools"

        try:
            amount = Decimal(amount)
        except Exception:
            return None, "Invalid amount"

        min_rsc = MINIMUM_FUNDRAISE_CONTRIBUTION_AMOUNT_RSC
        max_rsc = MAXIMUM_FUNDRAISE_CONTRIBUTION_AMOUNT_RSC
        if amount < min_rsc or amount > max_rsc:
            return None, f"Invalid amount. Minimum is {min_rsc}"

        return self.create_rsc_contribution(user, pool, amount, use_credits=use_credits)

    def create_rsc_contribution(
        self,
        user: User,
        pool: FundingPool,
        amount: Decimal,
        use_credits: bool = True,
    ) -> tuple[Purchase | None, str | None]:
        """
        Create an RSC contribution to a funding pool.

        When ``use_credits`` is True, the full ``amount + fee`` must be covered
        by funding credits. Otherwise, promotional RSC is consumed first and
        available RSC covers any remainder.
        """
        try:
            amount = Decimal(str(amount))
        except (ArithmeticError, TypeError, ValueError):
            return None, "Invalid amount"

        if not amount.is_finite() or amount <= 0:
            return None, "Invalid amount"

        fee, rh_fee, dao_fee, fee_object = calculate_bounty_fees(amount)
        total_cost = amount + fee

        if any(
            not value.is_finite() or value < 0
            for value in (fee, rh_fee, dao_fee, total_cost)
        ):
            return None, "Invalid fee configuration"

        with transaction.atomic():
            pool = FundingPool.objects.select_for_update().get(id=pool.id)
            if pool.status != FundingPool.OPEN:
                return None, "Funding pool is not open"

            user = User.objects.select_for_update().get(id=user.id)

            try:
                allocations = FundraiseService._allocate_contribution_spend(
                    user, total_cost, use_credits
                )
            except ValueError as error:
                return None, str(error)

            purchase = Purchase.objects.create(
                user=user,
                content_type=ContentType.objects.get_for_model(FundingPool),
                object_id=pool.id,
                purchase_method=Purchase.OFF_CHAIN,
                purchase_type=Purchase.FUNDING_POOL_CONTRIBUTION,
                paid_status=Purchase.PAID,
                amount=amount,
                rsc_usd_rate=RscExchangeRate.get_latest(),
            )

            deduct_bounty_fees(user, fee, rh_fee, dao_fee, fee_object)

            remaining_amount = amount

            for alloc in allocations:
                alloc_amount = alloc["amount"]
                amount_used = min(alloc_amount, remaining_amount)
                fee_used = alloc_amount - amount_used

                if amount_used > 0:
                    Balance.objects.create(
                        user=user,
                        content_type=ContentType.objects.get_for_model(Purchase),
                        object_id=purchase.id,
                        amount=f"-{amount_used.to_eng_string()}",
                        is_locked=alloc["is_locked"],
                        lock_type=alloc["lock_type"],
                        purchase=purchase,
                    )

                if fee_used > 0:
                    Balance.objects.create(
                        user=user,
                        content_type=ContentType.objects.get_for_model(BountyFee),
                        object_id=fee_object.id,
                        amount=f"-{fee_used.to_eng_string()}",
                        is_locked=alloc["is_locked"],
                        lock_type=alloc["lock_type"],
                        purchase=purchase,
                    )

                remaining_amount -= amount_used

            track_revenue_event.apply_async(
                (
                    user.id,
                    "FUNDING_POOL_CONTRIBUTION_FEE",
                    rh_fee.to_eng_string(),
                    None,
                    "OFF_CHAIN",
                ),
                priority=1,
            )

            pool.amount_holding += amount
            pool.save(update_fields=["amount_holding", "updated_date"])

        return purchase, None
