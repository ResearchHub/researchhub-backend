import time
from decimal import Decimal
from typing import Optional, Tuple

from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from analytics.tasks import track_revenue_event
from purchase.models import Balance, Fundraise, Purchase, UsdFundraiseContribution
from purchase.related_models.constants import USD_FUNDRAISE_FEE_PERCENT
from purchase.related_models.constants.currency import USD
from reputation.distributions import create_bounty_refund_distribution
from reputation.distributor import Distributor
from reputation.models import BountyFee, Escrow
from reputation.utils import calculate_bounty_fees, deduct_bounty_fees
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.models import User


class FundraiseService:
    """Service for managing fundraise-related operations."""

    def get_funder_overview(self, user: User) -> dict:
        """Return funder overview metrics for a given user."""
        return {}

    def get_grant_overview(self, user: User, grant_id: int) -> dict:
        """Return metrics for a specific grant."""
        return {}

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

    def refund_rsc_contributions(self, fundraise: "Fundraise") -> bool:
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

    def refund_usd_contributions(self, fundraise: "Fundraise") -> bool:
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

    def close_fundraise(self, fundraise: "Fundraise") -> bool:
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
