import logging
import time
from datetime import timedelta
from decimal import Decimal
from typing import Optional, Tuple

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from analytics.tasks import track_revenue_event
from purchase.endaoment import EndaomentService
from purchase.models import (
    Balance,
    EndaomentAccount,
    Fundraise,
    Purchase,
    RscExchangeRate,
    UsdFundraiseContribution,
)
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

USD_CONTRIBUTION_CSV_HEADERS = [
    "fundraise_id",
    "fundraise_status",
    "fundraise_goal_amount_usd",
    "document_title",
    "nonprofit_name",
    "contribution_id",
    "contributor_name",
    "contributor_email",
    "amount_usd",
    "fee_usd",
    "net_amount_usd",
    "origin_fund_id",
    "destination_org_id",
    "endaoment_transfer_id",
    "contribution_date",
    "status",
    "is_refunded",
]

logger = logging.getLogger(__name__)


class FundraiseService:
    """Service for managing fundraise-related operations."""

    def __init__(
        self,
        referral_bonus_service: ReferralBonusService = None,
        endaoment_service: EndaomentService = None,
    ):
        self.referral_bonus_service = referral_bonus_service or ReferralBonusService()
        self.endaoment_service = endaoment_service or EndaomentService()

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
            nonprofit_org = fundraise.get_nonprofit_org()
            if not nonprofit_org:
                return False, "Cannot contribute to your own fundraise"

        return True, None

    def create_contribution(
        self,
        user: User,
        fundraise: Fundraise,
        amount: Decimal,
        currency: str = RSC,
        check_self_contribution: bool = True,
        origin_fund_id: Optional[str] = None,
        use_credits: bool = True,
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
            origin_fund_id: The Endaoment fund (DAF) ID of the doner for USD grants
            use_credits: For RSC contributions, which balance pool pays for
                ``amount + fee``. When True, pay entirely from funding credits
                (locked balance); when False, pay entirely from unlocked RSC.
                Pools are never mixed. Ignored for USD contributions.

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

            return self.create_usd_contribution(
                user=user,
                fundraise=fundraise,
                amount_cents=amount_cents,
                origin_fund_id=origin_fund_id,
            )

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

            return self.create_rsc_contribution(
                user, fundraise, amount, use_credits=use_credits
            )

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
        self,
        user: User,
        fundraise: Fundraise,
        amount: Decimal,
        use_credits: bool = True,
    ) -> Tuple[Optional[Purchase], Optional[str]]:
        """
        Creates an RSC contribution to a fundraise.

        The contribution is funded exclusively from a single pool: when
        ``use_credits`` is True the full ``amount + fee`` must be covered by
        the user's funding credits (locked balance); when False, by unlocked
        RSC. Mixing the two pools is not allowed.

        Args:
            user: The user making the contribution
            fundraise: The fundraise to contribute to
            amount: The contribution amount in RSC
            use_credits: When True, pay entirely from funding credits (locked
                balance). When False, pay entirely from unlocked RSC.

        Returns:
            Tuple of (purchase, error_message). If successful, error_message is None.
            If failed, purchase is None and error_message contains the reason.
        """
        # Calculate fees
        fee, rh_fee, dao_fee, fee_object = calculate_bounty_fees(amount)
        total_cost = amount + fee

        with transaction.atomic():
            user = User.objects.select_for_update().get(id=user.id)

            if use_credits:
                if user.get_locked_balance() < total_cost:
                    return None, "Insufficient funding credits"
                allocations = [{"amount": total_cost, "is_locked": True}]
            else:
                if user.get_available_balance() < total_cost:
                    return None, "Insufficient balance"
                allocations = [{"amount": total_cost, "is_locked": False}]

            # Create purchase object
            purchase = Purchase.objects.create(
                user=user,
                content_type=ContentType.objects.get_for_model(Fundraise),
                object_id=fundraise.id,
                purchase_method=Purchase.OFF_CHAIN,
                purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
                paid_status=Purchase.PAID,
                amount=amount,
                rsc_usd_rate=RscExchangeRate.get_latest(),
            )

            # Deduct fees
            deduct_bounty_fees(user, fee, rh_fee, dao_fee, fee_object)

            # Create balance debit records, splitting each allocation across
            # the contribution amount and fee.
            remaining_amount = amount

            for alloc in allocations:
                alloc_amount = alloc["amount"]

                # Apply as much of this allocation to the contribution first,
                # then the remainder to fees.
                amount_used = min(alloc_amount, remaining_amount)
                fee_used = alloc_amount - amount_used

                if amount_used > 0:
                    Balance.objects.create(
                        user=user,
                        content_type=ContentType.objects.get_for_model(Purchase),
                        object_id=purchase.id,
                        amount=f"-{amount_used.to_eng_string()}",
                        is_locked=alloc["is_locked"],
                        purchase=purchase,
                    )

                if fee_used > 0:
                    Balance.objects.create(
                        user=user,
                        content_type=ContentType.objects.get_for_model(BountyFee),
                        object_id=fee_object.id,
                        amount=f"-{fee_used.to_eng_string()}",
                        is_locked=alloc["is_locked"],
                        purchase=purchase,
                    )

                remaining_amount -= amount_used

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
        self,
        user: User,
        fundraise: Fundraise,
        amount_cents: int,
        origin_fund_id: str = None,
    ) -> Tuple[Optional[UsdFundraiseContribution], Optional[str]]:
        """
        Creates a USD contribution to a fundraise.

        Args:
            user: The user making the contribution
            fundraise: The fundraise to contribute to
            amount_cents: The contribution amount in cents
            origin_fund_id: The Endaoment fund (DAF) ID for the grant transfer.

        Returns:
            Tuple of (contribution, error_message). If successful, error_message is None.
            If failed, contribution is None and error_message contains the reason.
        """
        # Calculate 9% fee
        fee_cents = (amount_cents * USD_FUNDRAISE_FEE_PERCENT) // 100
        total_amount_cents = amount_cents + fee_cents
        origin_fund_id = origin_fund_id or None
        endaoment_transfer_id = None
        destination_org_id = None

        with transaction.atomic():
            user = User.objects.select_for_update().get(id=user.id)

            if not origin_fund_id:
                return None, "origin_fund_id is required for USD contributions"

            # Store intended nonprofit org ID for later manual transfer/refund.
            nonprofit_org = fundraise.get_nonprofit_org()
            destination_org_id = (
                nonprofit_org.endaoment_org_id if nonprofit_org else None
            )
            if not destination_org_id:
                return None, "Fundraise nonprofit org is not set"

            try:
                # Note: The destination fund is ResearchHub's fund.
                # The actual transfer to the nonprofit org is handled manually.
                transfer_result = self.endaoment_service.transfer_to_researchhub_fund(
                    user=user,
                    origin_fund_id=origin_fund_id,
                    amount_cents=total_amount_cents,
                )
                endaoment_transfer_id = transfer_result.get("id")
            except EndaomentAccount.DoesNotExist:
                return None, "Endaoment account not connected"
            except Exception as e:
                logger.error(f"Failed to create Endaoment grant: {e}", exc_info=e)
                return None, "Failed to submit Endaoment grant"

            # Create the contribution record
            contribution = UsdFundraiseContribution.objects.create(
                user=user,
                fundraise=fundraise,
                amount_cents=amount_cents,
                fee_cents=fee_cents,
                status=UsdFundraiseContribution.Status.SUBMITTED,
                origin_fund_id=origin_fund_id,
                destination_org_id=destination_org_id,
                endaoment_transfer_id=endaoment_transfer_id,
            )

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

    def _refund_contribution_debit(
        self, fundraise, user, debit, purchase_ct, bounty_fee_ct
    ):
        """Refund a single debit entry. Returns True on success, False on failure."""
        abs_amount = abs(Decimal(debit.amount))
        if abs_amount == 0:
            return True

        if debit.content_type == purchase_ct:
            return fundraise.escrow.refund(user, abs_amount, is_locked=debit.is_locked)

        if debit.content_type == bounty_fee_ct:
            return self._refund_fee(user, debit, abs_amount)

        return True

    def _refund_fee(self, user, debit, abs_amount):
        """Refund a fee debit from the revenue account. Returns True on success."""
        rh_revenue_account = User.objects.get_revenue_account()
        fee_object = BountyFee.objects.get(id=debit.object_id)
        distribution = create_bounty_refund_distribution(abs_amount)
        distributor = Distributor(
            distribution,
            user,
            fee_object,
            time.time(),
            giver=rh_revenue_account,
            is_locked=debit.is_locked,
        )
        record = distributor.distribute()
        return record.distributed_status != "FAILED"

    def refund_rsc_contributions(self, fundraise: Fundraise) -> bool:
        """
        Refund all RSC contributions from escrow back to contributors.
        Also refunds the fees that were deducted when creating contributions.
        Preserves the locked/unlocked status of the original funds.
        Returns True if all refunds successful, False if any fail.
        """
        purchase_ct = ContentType.objects.get_for_model(Purchase)
        bounty_fee_ct = ContentType.objects.get_for_model(BountyFee)

        for contribution in fundraise.purchases.all():
            for debit in Balance.objects.filter(purchase=contribution):
                if not self._refund_contribution_debit(
                    fundraise, contribution.user, debit, purchase_ct, bounty_fee_ct
                ):
                    return False

        return True

    def refund_usd_contributions(self, fundraise: Fundraise) -> bool:
        """
        Mark all USD contributions as refunded/cancelled.
        Actual refunds are handled externally via Endaoment.
        """
        for usd_contribution in fundraise.usd_contributions.filter(is_refunded=False):
            usd_contribution.is_refunded = True
            usd_contribution.status = UsdFundraiseContribution.Status.CANCELLED
            usd_contribution.save(update_fields=["is_refunded", "status"])

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
            logger.error(f"Failed to process referral bonuses: {e}", exc_info=e)

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

    def reopen_fundraise(self, fundraise: Fundraise, duration_days: int) -> None:
        """
        Reopen a fundraise and set its end date `duration_days` days from now.
        Rejects COMPLETED fundraises because funds have already been paid out.

        Raises:
            ValueError: If fundraise is completed or duration_days is not a
                positive integer.
        """
        if not isinstance(duration_days, int) or duration_days <= 0:
            raise ValueError("duration_days must be a positive integer")

        with transaction.atomic():
            if fundraise.status == Fundraise.COMPLETED:
                raise ValueError("Cannot reopen a completed fundraise")

            fundraise.status = Fundraise.OPEN
            fundraise.end_date = timezone.now() + timedelta(days=duration_days)
            fundraise.save()

            if fundraise.escrow and fundraise.escrow.status == Escrow.CANCELLED:
                fundraise.escrow.set_pending_status()

    def export_usd_contributions(self, fundraise: Fundraise) -> list[list]:
        """
        Return all USD contributions for a given fundraise as rows for CSV export.
        Note: CSV headers are available in `USD_CONTRIBUTION_CSV_HEADERS`.
        """
        nonprofit_org = fundraise.get_nonprofit_org()
        nonprofit_name = nonprofit_org.name if nonprofit_org else ""

        document = fundraise.unified_document.get_document()
        document_title = document.title if document else ""

        contributions = (
            fundraise.usd_contributions.all()
            .select_related("user")
            .order_by("created_date")
        )

        rows = []
        for c in contributions.iterator():
            amount_usd = c.amount_cents / 100
            fee_usd = c.fee_cents / 100
            net_usd = (c.amount_cents - c.fee_cents) / 100
            contributor_name = f"{c.user.first_name} {c.user.last_name}".strip()

            rows.append(
                [
                    fundraise.id,
                    fundraise.status,
                    fundraise.goal_amount,
                    document_title,
                    nonprofit_name,
                    c.id,
                    contributor_name,
                    c.user.email,
                    f"{amount_usd:.2f}",
                    f"{fee_usd:.2f}",
                    f"{net_usd:.2f}",
                    c.origin_fund_id,
                    c.destination_org_id,
                    c.endaoment_transfer_id or "",
                    c.created_date.strftime("%Y-%m-%d %H:%M:%S"),
                    c.status,
                    c.is_refunded,
                ]
            )

        return rows
