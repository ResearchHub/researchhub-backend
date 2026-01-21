from datetime import datetime, timedelta
from decimal import Decimal

import pytz
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.fields import GenericRelation
from django.db import models
from django.db.models import Sum
from django.db.models.functions import Coalesce

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

    def get_usd_contributors(self):
        """Returns USD contributions with user data."""
        return self.usd_contributions.select_related("user")

    def get_amount_raised(self, currency=USD):
        """
        Get the net amount raised from both RSC (via escrow) and USD contributions.
        RSC amounts are calculated from escrow holdings. USD amounts are calculated
        live from UsdFundraiseContribution records.
        """
        # Calculate RSC amount from escrow
        rsc_amount = 0.0
        if self.escrow:
            rsc_amount = float(self.escrow.amount_holding + self.escrow.amount_paid)

        # Calculate USD amount from contributions (in cents)
        usd_cents = self.usd_contributions.aggregate(
            total=Coalesce(Sum("amount_cents"), 0)
        )["total"]
        usd_from_contributions = usd_cents / 100.0

        if currency == USD:
            usd_from_rsc = (
                RscExchangeRate.rsc_to_usd(rsc_amount) if rsc_amount > 0 else 0
            )
            return usd_from_rsc + usd_from_contributions

        if currency == RSC:
            rsc_from_usd = (
                RscExchangeRate.usd_to_rsc(usd_from_contributions)
                if usd_from_contributions > 0
                else 0
            )
            return rsc_amount + rsc_from_usd

        if currency == ETHER:
            # Convert both RSC and USD to ETH
            eth_from_rsc = (
                RscExchangeRate.rsc_to_eth(rsc_amount) if rsc_amount > 0 else 0
            )
            rsc_from_usd = (
                RscExchangeRate.usd_to_rsc(usd_from_contributions)
                if usd_from_contributions > 0
                else 0
            )
            eth_from_usd = (
                RscExchangeRate.rsc_to_eth(rsc_from_usd) if rsc_from_usd > 0 else 0
            )
            return eth_from_rsc + eth_from_usd

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
