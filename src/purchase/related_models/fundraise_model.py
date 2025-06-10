import time
from datetime import datetime, timedelta
from decimal import Decimal

import pytz
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.fields import GenericRelation
from django.db import models, transaction

from purchase.related_models.constants.currency import ETHER, RSC, USD
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from utils.models import DefaultModel


def get_default_expiration_date():
    now = datetime.now(pytz.UTC)
    date = now + timedelta(days=30)
    return date


class Fundraise(DefaultModel):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    COMPLETED = "COMPLETED"
    status_choices = (
        (OPEN, OPEN),
        (CLOSED, CLOSED),
        (COMPLETED, COMPLETED),
    )

    created_by = models.ForeignKey(
        "user.User", on_delete=models.CASCADE, related_name="fundraises"
    )
    unified_document = models.ForeignKey(
        "researchhub_document.ResearchhubUnifiedDocument",
        on_delete=models.CASCADE,
        related_name="fundraises",
    )
    escrow = models.ForeignKey(
        "reputation.Escrow",
        blank=True,
        null=True,
        on_delete=models.CASCADE,
        related_name="fundraises",
    )
    purchases = GenericRelation(
        "purchase.Purchase",
        object_id_field="object_id",
        content_type_field="content_type",
        related_query_name="fundraise",
    )
    status = models.CharField(choices=status_choices, default=OPEN, max_length=32)

    # value fields
    goal_amount = models.DecimalField(default=0, decimal_places=10, max_digits=19)
    goal_currency = models.CharField(max_length=16, default=USD)

    # time fields
    start_date = models.DateTimeField(auto_now_add=True)
    end_date = models.DateTimeField(
        blank=True,
        null=True,
        # default expiration to 30 days from now
        default=get_default_expiration_date,
    )

    class Meta:
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["end_date"]),
        ]

    def is_expired(self):
        if self.end_date:
            return self.end_date < datetime.now(pytz.UTC)
        return False

    def get_amount_raised(self, currency=USD):
        """
        Get the net amount raised by looking at the escrow's current holdings
        and amount paid out. This automatically accounts for refunds since
        refunds reduce the escrow's amount_holding.
        """
        if not self.escrow:
            return 0

        # The actual amount raised is what's currently held plus what's been paid out
        rsc_amount = float(self.escrow.amount_holding + self.escrow.amount_paid)

        if rsc_amount <= 0:
            return 0

        if currency == USD:
            usd_amount = RscExchangeRate.rsc_to_usd(rsc_amount)
            return usd_amount

        if currency == RSC:
            return rsc_amount

        if currency == ETHER:
            eth_amount = RscExchangeRate.rsc_to_eth(rsc_amount)
            return eth_amount

        raise ValueError("Invalid currency")

    def get_recipient(self):
        """
        Get the appropriate recipient for fundraise funds.
        If the fundraise is linked to a nonprofit, return the Endaoment account.
        Otherwise, return the original creator.
        """
        # Import inside method to avoid circular imports
        from organizations.models import NonprofitFundraiseLink

        nonprofit_link = NonprofitFundraiseLink.objects.filter(fundraise=self).first()

        if nonprofit_link:
            if not settings.ENDAOMENT_ACCOUNT_ID:
                raise ValueError(
                    "Fundraise is linked to a nonprofit but "
                    "ENDAOMENT_ACCOUNT_ID is not configured"
                )

            user_model = get_user_model()
            return user_model.objects.get(id=settings.ENDAOMENT_ACCOUNT_ID)

        return self.created_by

    def payout_funds(self):
        if not self.created_by:
            return

        # escrow.payout() expects a Decimal object
        recipient = self.get_recipient()

        payout_amount = self.get_amount_raised(currency=RSC)
        if isinstance(payout_amount, float):
            payout_amount = Decimal(str(payout_amount))

        did_payout = self.escrow.payout(
            recipient=recipient,
            payout_amount=payout_amount,
        )

        return did_payout

    def close_fundraise(self):
        """
        Close a fundraise and refund all contributions to their contributors.
        Also refunds the fees that were deducted when creating contributions.
        Only works if the fundraise is in OPEN status and has escrow funds.
        Returns True if successful, False otherwise.
        """
        # Import inside method to avoid circular imports
        from reputation.distributions import create_bounty_refund_distribution
        from reputation.distributor import Distributor
        from reputation.utils import calculate_bounty_fees
        from user.models import User

        with transaction.atomic():
            # Check if fundraise can be refunded (is open and has escrow funds)
            if self.status != self.OPEN or self.escrow.amount_holding <= 0:
                return False

            # Get all purchases (contributions) for this fundraise
            contributions = self.purchases.all()

            # Refund each contributor
            for contribution in contributions:
                user = contribution.user
                amount = Decimal(contribution.amount)

                # Only refund what's still in escrow
                if amount > 0:
                    success = self.escrow.refund(user, amount)
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

            # Update fundraise status
            self.status = self.CLOSED
            self.save()

            # Update escrow status
            self.escrow.set_cancelled_status()

            return True
