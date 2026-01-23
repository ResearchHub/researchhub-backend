from decimal import Decimal
from typing import Optional, Tuple

from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from analytics.tasks import track_revenue_event
from purchase.models import Balance, Fundraise, FundingCredit, Purchase, UsdFundraiseContribution
from purchase.related_models.constants import USD_FUNDRAISE_FEE_PERCENT
from purchase.related_models.constants.currency import USD
from purchase.services.funding_credit_service import FundingCreditService
from reputation.models import BountyFee, Escrow
from reputation.utils import calculate_bounty_fees, deduct_bounty_fees
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.models import User


class FundraiseService:
    """
    Service for managing fundraise-related operations.
    """

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

    def create_funding_credit_contribution(
        self, user: User, fundraise: Fundraise, amount: Decimal
    ) -> Tuple[Optional[Purchase], Optional[str]]:
        """
        Creates a contribution to a fundraise using funding credits.

        Funding credits are non-liquid rewards earned from staking RSC.
        They can only be spent on funding research proposals.

        Note: No fees are charged for funding credit contributions since
        credits are already a reward mechanism.

        Args:
            user: The user making the contribution
            fundraise: The fundraise to contribute to
            amount: The contribution amount in funding credits

        Returns:
            Tuple of (purchase, error_message). If successful, error_message is None.
            If failed, purchase is None and error_message contains the reason.
        """
        funding_credit_service = FundingCreditService()

        with transaction.atomic():
            user = User.objects.select_for_update().get(id=user.id)

            # Spend funding credits (this validates balance)
            credit_record, error = funding_credit_service.spend_credits(
                user, amount, fundraise
            )

            if error:
                return None, error

            # Create purchase record for tracking
            purchase = Purchase.objects.create(
                user=user,
                content_type=ContentType.objects.get_for_model(Fundraise),
                object_id=fundraise.id,
                purchase_method=Purchase.OFF_CHAIN,
                purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
                paid_status=Purchase.PAID,
                amount=amount,
            )

            # Track in Amplitude
            track_revenue_event.apply_async(
                (
                    user.id,
                    "FUNDRAISE_CONTRIBUTION_FUNDING_CREDITS",
                    str(amount),
                    None,
                    "FUNDING_CREDITS",
                ),
                priority=1,
            )

            # Update escrow object (credits are treated as RSC-equivalent)
            fundraise.escrow.amount_holding += amount
            fundraise.escrow.save()

        return purchase, None
