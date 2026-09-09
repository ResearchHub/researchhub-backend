import logging
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from analytics.tasks import track_revenue_event
from purchase.models import (
    Balance,
    FundingDistribution,
    FundingPool,
    Fundraise,
    Grant,
    GrantApplication,
    Purchase,
    RscExchangeRate,
)
from purchase.related_models.constants import (
    MAXIMUM_FUNDRAISE_CONTRIBUTION_AMOUNT_RSC,
    MINIMUM_FUNDRAISE_CONTRIBUTION_AMOUNT_RSC,
)
from purchase.related_models.constants.currency import RSC
from purchase.services.fundraise_service import FundraiseService
from reputation.models import BountyFee, Escrow
from reputation.utils import calculate_bounty_fees, deduct_bounty_fees
from user.models import User

logger = logging.getLogger(__name__)


class FundingPoolService:
    """Service for FundingPool contributions, distributions, and lifecycle helpers."""

    def create_pool_for_grant(self, grant: Grant) -> FundingPool:
        """Create the community contribution pot for a grant (one pool per grant)."""
        pool, _created = FundingPool.objects.get_or_create(
            grant=grant,
            defaults={"created_by": grant.created_by},
        )
        return pool

    def create_contribution(
        self,
        user: User,
        pool: FundingPool,
        amount: Decimal,
        currency: str = RSC,
        use_credits: bool = True,
    ) -> Purchase:
        """
        Validate and create an RSC contribution to a funding pool.

        Fees and balance debits follow the fundraise pattern;
        net amount is credited to ``pool.amount_holding``.

        Raises:
            ValueError: If the pool, currency, or amount is invalid.
        """
        if not pool.is_valid_for_contribution:
            raise ValueError("Funding pool is not open")

        if currency != RSC:
            raise ValueError("Only RSC contributions are supported for funding pools")

        try:
            amount = Decimal(amount)
        except Exception as error:
            raise ValueError("Invalid amount") from error

        min_rsc = MINIMUM_FUNDRAISE_CONTRIBUTION_AMOUNT_RSC
        max_rsc = MAXIMUM_FUNDRAISE_CONTRIBUTION_AMOUNT_RSC
        if amount < min_rsc or amount > max_rsc:
            raise ValueError(f"Invalid amount. Minimum is {min_rsc}")

        return self.create_rsc_contribution(user, pool, amount, use_credits=use_credits)

    def create_rsc_contribution(
        self,
        user: User,
        pool: FundingPool,
        amount: Decimal,
        use_credits: bool = True,
    ) -> Purchase:
        """
        Create an RSC contribution to a funding pool.

        When ``use_credits`` is True, the full ``amount + fee`` must be covered
        by funding credits. Otherwise, promotional RSC is consumed first and
        available RSC covers any remainder.

        Raises:
            ValueError: If amount, fees, pool status, or balance is invalid.
        """
        try:
            amount = Decimal(str(amount))
        except (ArithmeticError, TypeError, ValueError) as error:
            raise ValueError("Invalid amount") from error

        if not amount.is_finite() or amount <= 0:
            raise ValueError("Invalid amount")

        fee, rh_fee, dao_fee, fee_object = calculate_bounty_fees(amount)
        total_cost = amount + fee

        if any(
            not value.is_finite() or value < 0
            for value in (fee, rh_fee, dao_fee, total_cost)
        ):
            raise ValueError("Invalid fee configuration")

        with transaction.atomic():
            pool = (
                FundingPool.objects.select_for_update()
                .select_related("grant")
                .get(id=pool.id)
            )
            if not pool.is_valid_for_contribution:
                raise ValueError("Funding pool is not open")

            user = User.objects.select_for_update().get(id=user.id)

            allocations = FundraiseService._allocate_contribution_spend(
                user, total_cost, use_credits
            )

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

        return purchase

    def _resolve_distribution_target(
        self,
        pool: FundingPool,
        application_id: int,
    ) -> tuple[GrantApplication, Fundraise]:
        """Resolve a grant application and its proposal fundraise for distribution.

        The application must belong to the same grant as ``pool``.

        Raises:
            ValueError: If the application or proposal fundraise cannot be used.
        """
        try:
            application = GrantApplication.objects.select_related(
                "preregistration_post"
            ).get(id=application_id)
        except GrantApplication.DoesNotExist as error:
            raise ValueError("Grant application does not exist") from error

        if application.grant_id != pool.grant_id:
            raise ValueError("Application does not belong to this grant")

        fundraise = (
            Fundraise.objects.filter(
                unified_document_id=application.preregistration_post.unified_document_id,
            )
            .order_by("-created_date")
            .first()
        )
        if fundraise is None:
            raise ValueError("Proposal fundraise does not exist")

        return application, fundraise

    def distribute(
        self,
        pool: FundingPool,
        distributed_by: User,
        amount: Decimal,
        application_id: int,
    ) -> FundingDistribution:
        """
        Move RSC from a funding pool into an OPEN proposal fundraise escrow.

        Creates an audit ``Purchase`` on the proposal fundraise with no user
        Balance debit and no second bounty fee (fees were taken on contribute).

        Raises:
            ValueError: If amount, pool, application, or fundraise is invalid.
        """
        try:
            amount = Decimal(str(amount))
        except (ArithmeticError, TypeError, ValueError) as error:
            raise ValueError("Invalid amount") from error

        if not amount.is_finite() or amount <= 0:
            raise ValueError("Invalid amount")

        application, fundraise = self._resolve_distribution_target(pool, application_id)

        with transaction.atomic():
            pool = FundingPool.objects.select_for_update().get(id=pool.id)
            if not pool.is_valid_for_distribution:
                raise ValueError("Funding pool is not open")

            if amount > pool.amount_holding:
                raise ValueError("Insufficient pool balance")

            fundraise = Fundraise.objects.select_for_update().get(id=fundraise.id)
            if fundraise.status != Fundraise.OPEN:
                raise ValueError("Fundraise is not open")
            if fundraise.is_expired():
                raise ValueError("Fundraise is expired")
            if not fundraise.escrow_id:
                raise ValueError("Fundraise escrow is not set")

            escrow = Escrow.objects.select_for_update().get(id=fundraise.escrow_id)

            pool.amount_holding -= amount
            pool.amount_distributed += amount
            pool.save(
                update_fields=[
                    "amount_holding",
                    "amount_distributed",
                    "updated_date",
                ]
            )

            # Audit row only — no Balance debit;
            purchase = Purchase.objects.create(
                user=distributed_by,
                content_type=ContentType.objects.get_for_model(Fundraise),
                object_id=fundraise.id,
                purchase_method=Purchase.OFF_CHAIN,
                purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
                paid_status=Purchase.PAID,
                amount=amount,
                rsc_usd_rate=RscExchangeRate.get_latest(),
            )

            escrow.amount_holding += amount
            escrow.save(update_fields=["amount_holding", "updated_date"])

            distribution = FundingDistribution.objects.create(
                pool=pool,
                distributed_by=distributed_by,
                amount=amount,
                application=application,
                target_fundraise=fundraise,
                fundraise_purchase=purchase,
                status=FundingDistribution.APPLIED,
            )

        return distribution
