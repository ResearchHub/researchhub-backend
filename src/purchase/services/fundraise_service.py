import time
from decimal import Decimal
from typing import Optional, Tuple

from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from analytics.tasks import track_revenue_event
from purchase.models import Balance, Fundraise, Purchase, UsdFundraiseContribution
from purchase.related_models.constants import (
    MAXIMUM_FUNDRAISE_CONTRIBUTION_AMOUNT_RSC,
    MAXIMUM_FUNDRAISE_CONTRIBUTION_AMOUNT_USD_CENTS,
    MINIMUM_FUNDRAISE_CONTRIBUTION_AMOUNT_RSC,
    MINIMUM_FUNDRAISE_CONTRIBUTION_AMOUNT_USD_CENTS,
    USD_FUNDRAISE_FEE_PERCENT,
)
from purchase.related_models.constants.currency import RSC, USD
from referral.services.referral_bonus_service import ReferralBonusService
from reputation.distributions import create_bounty_refund_distribution
from reputation.distributor import Distributor
from reputation.models import BountyFee, Escrow
from reputation.utils import calculate_bounty_fees, deduct_bounty_fees
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.models import User
from utils.sentry import log_error


class FundraiseService:
    """
    Service for managing fundraise-related operations.
    """

    def __init__(self, referral_bonus_service: ReferralBonusService = None):
        self.referral_bonus_service = referral_bonus_service or ReferralBonusService()

    def validate_fundraise_for_contribution(
        self, fundraise: Fundraise, user: User, check_self_contribution: bool = True
    ) -> Tuple[bool, Optional[str]]:
        """
        Validates that a fundraise is valid for contributions.

        Args:
            fundraise: The fundraise to validate
            user: The user attempting to contribute
            check_self_contribution: Whether to check if user is contributing to own fundraise

        Returns:
            Tuple of (is_valid, error_message). If valid, error_message is None.
        """
        if fundraise.status != Fundraise.OPEN:
            return False, "Fundraise is not open"

        if fundraise.is_expired():
            return False, "Fundraise is expired"

        if check_self_contribution and fundraise.created_by.id == user.id:
            return False, "Cannot contribute to your own fundraise"

        return True, None

    def create_contribution(
        self,
        user: User,
        fundraise: Fundraise,
        amount: Decimal,
        currency: str = RSC,
        check_self_contribution: bool = True,
    ) -> Tuple[Optional[Purchase], Optional[str]]:
        """
        Validates and creates a contribution to a fundraise.
        Handles both RSC and USD contributions with limit validation.

        Args:
            user: The user making the contribution
            fundraise: The fundraise to contribute to
            amount: The contribution amount (RSC as Decimal, USD in cents as int)
            currency: The currency type (RSC or USD)
            check_self_contribution: Whether to check if user is contributing to own fundraise

        Returns:
            Tuple of (contribution, error_message). If successful, error_message is None.
            If failed, contribution is None and error_message contains the reason.
        """
        # Validate fundraise
        is_valid, error = self.validate_fundraise_for_contribution(
            fundraise, user, check_self_contribution
        )
        if not is_valid:
            return None, error

        if currency == USD:
            # USD contributions use cents
            try:
                amount_cents = int(amount)
            except (ValueError, TypeError):
                return None, "Invalid amount"

            # Check if amount is within limits
            if (
                amount_cents < MINIMUM_FUNDRAISE_CONTRIBUTION_AMOUNT_USD_CENTS
                or amount_cents > MAXIMUM_FUNDRAISE_CONTRIBUTION_AMOUNT_USD_CENTS
            ):
                min_dollars = MINIMUM_FUNDRAISE_CONTRIBUTION_AMOUNT_USD_CENTS / 100
                return None, f"Invalid amount. Minimum is ${min_dollars:.2f}"

            return self.create_usd_contribution(user, fundraise, amount_cents)

        else:
            # RSC contributions
            try:
                amount = Decimal(amount)
            except Exception:
                return None, "Invalid amount"

            # Check if amount is within limits
            if (
                amount < MINIMUM_FUNDRAISE_CONTRIBUTION_AMOUNT_RSC
                or amount > MAXIMUM_FUNDRAISE_CONTRIBUTION_AMOUNT_RSC
            ):
                return None, (
                    f"Invalid amount. Minimum is "
                    f"{MINIMUM_FUNDRAISE_CONTRIBUTION_AMOUNT_RSC}"
                )

            return self.create_rsc_contribution(user, fundraise, amount)

    def create_fundraise_with_escrow(
        self,
        user: User,
        unified_document: ResearchhubUnifiedDocument,
        goal_amount: Decimal,
        goal_currency: str = USD,
        status: str = Fundraise.OPEN,
    ) -> Fundraise:
        """
        Creates a fundraise with its associated escrow.
        All input validation is handled by FundraiseCreateSerializer.
        """
        fundraise = Fundraise.objects.create(
            created_by=user,
            unified_document=unified_document,
            goal_amount=goal_amount,
            goal_currency=goal_currency,
            status=status,
        )

        escrow = Escrow.objects.create(
            created_by=user,
            hold_type=Escrow.FUNDRAISE,
            content_type=ContentType.objects.get_for_model(Fundraise),
            object_id=fundraise.id,
        )
        fundraise.escrow = escrow
        fundraise.save()

        return fundraise

    def create_rsc_contribution(
        self, user: User, fundraise: Fundraise, amount: Decimal
    ) -> Tuple[Optional[Purchase], Optional[str]]:
        """
        Creates an RSC contribution to a fundraise.

        Args:
            user: The user making the contribution
            fundraise: The fundraise to contribute to
            amount: The contribution amount in RSC

        Returns:
            Tuple of (purchase, error_message). If successful, error_message is None.
            If failed, purchase is None and error_message contains the reason.
        """
        # Calculate fees
        fee, rh_fee, dao_fee, fee_object = calculate_bounty_fees(amount)

        with transaction.atomic():
            user = User.objects.select_for_update().get(id=user.id)

            # Check if user has enough balance in their wallet
            # For fundraise contributions, we allow using locked balance
            user_balance = user.get_balance(include_locked=True)
            if user_balance - (amount + fee) < 0:
                return None, "Insufficient balance"

            # Create purchase object
            purchase = Purchase.objects.create(
                user=user,
                content_type=ContentType.objects.get_for_model(Fundraise),
                object_id=fundraise.id,
                purchase_method=Purchase.OFF_CHAIN,
                purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
                paid_status=Purchase.PAID,
                amount=amount,
            )

            # Deduct fees
            deduct_bounty_fees(user, fee, rh_fee, dao_fee, fee_object)

            # Get user's available locked balance
            available_locked_balance = user.get_locked_balance()

            # Determine how to split the contribution amount
            locked_amount_used = min(available_locked_balance, amount)
            regular_amount_used = amount - locked_amount_used

            # Determine how to split the fees using remaining locked balance
            remaining_locked_balance = available_locked_balance - locked_amount_used
            locked_fee_used = min(remaining_locked_balance, fee)
            regular_fee_used = fee - locked_fee_used

            # Create balance records for the contribution amount
            if locked_amount_used > 0:
                Balance.objects.create(
                    user=user,
                    content_type=ContentType.objects.get_for_model(Purchase),
                    object_id=purchase.id,
                    amount=f"-{locked_amount_used.to_eng_string()}",
                    is_locked=True,
                    lock_type=Balance.LockType.REFERRAL_BONUS,
                )

            if regular_amount_used > 0:
                Balance.objects.create(
                    user=user,
                    content_type=ContentType.objects.get_for_model(Purchase),
                    object_id=purchase.id,
                    amount=f"-{regular_amount_used.to_eng_string()}",
                )

            # Create balance records for the fees
            if locked_fee_used > 0:
                Balance.objects.create(
                    user=user,
                    content_type=ContentType.objects.get_for_model(BountyFee),
                    object_id=fee_object.id,
                    amount=f"-{locked_fee_used.to_eng_string()}",
                    is_locked=True,
                    lock_type=Balance.LockType.REFERRAL_BONUS,
                )

            if regular_fee_used > 0:
                Balance.objects.create(
                    user=user,
                    content_type=ContentType.objects.get_for_model(BountyFee),
                    object_id=fee_object.id,
                    amount=f"-{regular_fee_used.to_eng_string()}",
                )

            # Track in Amplitude
            rh_fee_str = rh_fee.to_eng_string()
            track_revenue_event.apply_async(
                (
                    user.id,
                    "FUNDRAISE_CONTRIBUTION_FEE",
                    rh_fee_str,
                    None,
                    "OFF_CHAIN",
                ),
                priority=1,
            )

            # Update escrow object
            fundraise.escrow.amount_holding += amount
            fundraise.escrow.save()

        return purchase, None

    def create_usd_contribution(
        self, user: User, fundraise: Fundraise, amount_cents: int
    ) -> Tuple[Optional[UsdFundraiseContribution], Optional[str]]:
        """
        Creates a USD contribution to a fundraise.

        Args:
            user: The user making the contribution
            fundraise: The fundraise to contribute to
            amount_cents: The contribution amount in cents

        Returns:
            Tuple of (contribution, error_message). If successful, error_message is None.
            If failed, contribution is None and error_message contains the reason.
        """
        # Calculate 9% fee
        fee_cents = (amount_cents * USD_FUNDRAISE_FEE_PERCENT) // 100
        total_amount_cents = amount_cents + fee_cents

        with transaction.atomic():
            user = User.objects.select_for_update().get(id=user.id)

            # Check if user has enough USD balance
            user_usd_balance = user.get_usd_balance_cents()
            if user_usd_balance < total_amount_cents:
                return None, "Insufficient USD balance"

            # Create the contribution record
            contribution = UsdFundraiseContribution.objects.create(
                user=user,
                fundraise=fundraise,
                amount_cents=amount_cents,
                fee_cents=fee_cents,
            )

            # Deduct total amount (contribution + fee) from user's USD balance
            user.decrease_usd_balance(total_amount_cents, source=contribution)

            # Track in Amplitude
            fee_dollars = fee_cents / 100.0
            track_revenue_event.apply_async(
                (
                    user.id,
                    "FUNDRAISE_CONTRIBUTION_FEE_USD",
                    str(fee_dollars),
                    None,
                    "USD",
                ),
                priority=1,
            )

        return contribution, None

    def refund_rsc_contributions(self, fundraise: Fundraise) -> bool:
        """
        Refund all RSC contributions from escrow back to contributors.
        Also refunds the fees that were deducted when creating contributions.
        Returns True if all refunds successful, False if any fail.
        """
        # Get all purchases (RSC contributions) for this fundraise
        contributions = fundraise.purchases.all()

        # Refund each RSC contributor
        for contribution in contributions:
            user = contribution.user
            amount = Decimal(contribution.amount)

            # Only refund what's still in escrow
            if amount > 0:
                success = fundraise.escrow.refund(user, amount)
                if not success:
                    # If a refund fails, we should abort the whole transaction
                    return False

            # Also refund the fees that were deducted when this contribution
            # was made. Calculate the fee using the same logic used during
            # contribution creation.
            fee, _, _, fee_object = calculate_bounty_fees(amount)

            if fee > 0:
                # Create a refund for the fee
                rh_revenue_account = User.objects.get_revenue_account()
                distribution = create_bounty_refund_distribution(fee)
                distributor = Distributor(
                    distribution,
                    user,
                    fee_object,  # The BountyFee object
                    time.time(),
                    giver=rh_revenue_account,
                )
                record = distributor.distribute()
                if record.distributed_status == "FAILED":
                    # If fee refund fails, we should abort the whole
                    # transaction
                    return False

        return True

    def refund_usd_contributions(self, fundraise: Fundraise) -> bool:
        """
        Refund all USD contributions that haven't been refunded yet.
        Refunds both the contribution amount and the fee to the user's USD balance.
        """
        for usd_contribution in fundraise.usd_contributions.filter(is_refunded=False):
            user = usd_contribution.user
            # Refund both the contribution amount and the fee
            total_refund_cents = (
                usd_contribution.amount_cents + usd_contribution.fee_cents
            )
            if total_refund_cents > 0:
                user.increase_usd_balance(total_refund_cents, source=usd_contribution)
            # Mark as refunded
            usd_contribution.is_refunded = True
            usd_contribution.save(update_fields=["is_refunded"])

        return True

    def complete_fundraise(self, fundraise: Fundraise) -> None:
        """
        Complete a fundraise and payout funds to the recipient.
        Only works if the fundraise is in OPEN status and has escrow funds.

        Args:
            fundraise: The fundraise to complete

        Raises:
            ValueError: If fundraise is not open or has no funds to payout
            RuntimeError: If payout fails
        """
        with transaction.atomic():
            if fundraise.status != Fundraise.OPEN:
                raise ValueError("Fundraise is not open")

            if not fundraise.escrow or fundraise.escrow.amount_holding <= 0:
                raise ValueError("Fundraise has no funds to payout")

            if not fundraise.payout_funds():
                raise RuntimeError("Failed to payout funds")

            fundraise.status = Fundraise.COMPLETED
            fundraise.save()

        # Process referral bonuses (outside transaction to not block payout on failure)
        try:
            self.referral_bonus_service.process_fundraise_completion(fundraise)
        except Exception as e:
            log_error(e, message="Failed to process referral bonuses")

    def close_fundraise(self, fundraise: Fundraise) -> bool:
        """
        Close a fundraise and refund all contributions to their contributors.
        Also refunds the fees that were deducted when creating contributions.
        Only works if the fundraise is in OPEN status.
        Returns True if successful, False otherwise.
        """
        with transaction.atomic():
            # Check if fundraise can be closed (must be open)
            if fundraise.status != Fundraise.OPEN:
                return False

            # Refund RSC contributions
            if not self.refund_rsc_contributions(fundraise):
                return False

            # Refund USD contributions
            if not self.refund_usd_contributions(fundraise):
                return False

            # Update fundraise status
            fundraise.status = Fundraise.CLOSED
            fundraise.save()

            # Update escrow status
            fundraise.escrow.set_cancelled_status()

            return True
