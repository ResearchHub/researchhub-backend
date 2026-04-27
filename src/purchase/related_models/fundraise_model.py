from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    from user.models import User


@dataclass
class FundraiseContributionEvent:
    """
    Represents a single contribution to a fundraise, including the amount,
    currency, and date of the contribution.
    """

    amount: float
    currency: str
    date: datetime


@dataclass
class FundraiseContributorSummary:
    """
    Summary of a single contributor to a fundraise, including USD and RSC totals
    and a list of individual contributions.
    """

    user: User
    total_rsc: float
    """
    The total amount of RSC contributed by the user.
    """
    total_rsc_usd_snapshot: float
    """
    The USD value of the RSC contributions, captured at the time
    of each contribution using the RSC-to-USD exchange rate.
    """
    total_usd: float
    """
    The total amount of USD contributed by the user.
    This does not include the cost basis of any RSC contributions.
    """
    contributions: list[FundraiseContributionEvent]


@dataclass
class FundraiseContributorsSummary:
    """
    Summary of contributors to a fundraise, including the total number of contributors.
    """

    total: int
    top: list[FundraiseContributorSummary]


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

    def get_contributors_summary(self) -> FundraiseContributorsSummary:
        """
        Aggregate contributor totals across both RSC and USD contributions
        which can be used for serialization, for example.
        """
        rsc_contributions = getattr(self, "prefetched_purchases", None)
        if rsc_contributions is None:
            rsc_contributions = self.purchases.select_related("user").order_by(
                "-created_date"
            )

        usd_contributions = getattr(self, "prefetched_usd_contributions", None)
        if usd_contributions is None:
            usd_contributions = (
                self.usd_contributions.select_related("user")
                .filter(is_refunded=False)
                .order_by("-created_date")
            )

        rsc_contributions = list(rsc_contributions)
        usd_contributions = list(usd_contributions)

        user_data = {}
        for contribution in rsc_contributions + usd_contributions:
            user_id = contribution.user_id
            if user_id not in user_data:
                user_data[user_id] = {
                    "user": contribution.user,
                    "total_rsc": 0,
                    "total_rsc_usd_snapshot": 0,
                    "total_usd": 0,
                    "contributions": [],
                }

        for contribution in rsc_contributions:
            amount = float(contribution.amount)
            if contribution.rsc_usd_rate is not None:
                usd_value = amount * contribution.rsc_usd_rate
            else:
                usd_value = RscExchangeRate.rsc_to_usd(amount)
            user_data[contribution.user_id]["total_rsc"] += amount
            user_data[contribution.user_id]["total_rsc_usd_snapshot"] += usd_value
            user_data[contribution.user_id]["contributions"].append(
                FundraiseContributionEvent(
                    amount=amount,
                    currency=RSC,
                    date=contribution.created_date,
                )
            )

        for contribution in usd_contributions:
            amount = contribution.amount_cents / 100.0
            user_data[contribution.user_id]["total_usd"] += amount
            user_data[contribution.user_id]["contributions"].append(
                FundraiseContributionEvent(
                    amount=amount,
                    currency=USD,
                    date=contribution.created_date,
                )
            )

        result = []
        for data in user_data.values():
            result.append(
                FundraiseContributorSummary(
                    user=data["user"],
                    total_rsc=data["total_rsc"],
                    total_usd=data["total_usd"],
                    total_rsc_usd_snapshot=data["total_rsc_usd_snapshot"],
                    contributions=sorted(
                        data["contributions"],
                        key=lambda x: x.date,
                        reverse=True,
                    ),
                )
            )

        result = sorted(
            result,
            key=lambda x: x.total_usd + RscExchangeRate.rsc_to_usd(x.total_rsc),
            reverse=True,
        )

        return FundraiseContributorsSummary(
            total=len(user_data),
            top=result,
        )

    def get_amount_raised(self, currency=USD, rsc_to_usd_rate=None):
        """
        Get the net amount raised from both RSC (via escrow) and USD contributions.
        RSC amounts are calculated from escrow holdings. USD amounts are calculated
        live from UsdFundraiseContribution records.

        When ``currency`` is USD, an explicit ``rsc_to_usd_rate`` may be provided
        (e.g. a multi-day average) to value RSC at a rate other than the latest.
        """
        # Calculate RSC amount from escrow
        rsc_amount = 0.0
        if self.escrow:
            rsc_amount = float(self.escrow.amount_holding + self.escrow.amount_paid)

        # Calculate USD amount from contributions (in cents), excluding refunded ones
        usd_cents = self.usd_contributions.filter(is_refunded=False).aggregate(
            total=Coalesce(Sum("amount_cents"), 0)
        )["total"]
        usd_from_contributions = usd_cents / 100.0

        if currency == USD:
            if rsc_amount > 0:
                if rsc_to_usd_rate is not None:
                    usd_from_rsc = rsc_amount * rsc_to_usd_rate
                else:
                    usd_from_rsc = RscExchangeRate.rsc_to_usd(rsc_amount)
            else:
                usd_from_rsc = 0
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

    def get_nonprofit_org(self):
        """
        Return the nonprofit org if the fundraise is linked, otherwise None.
        """
        # Avoid circular imports
        from organizations.models import NonprofitFundraiseLink

        nonprofit_link = (
            NonprofitFundraiseLink.objects.select_related("nonprofit")
            .filter(fundraise=self)
            .first()
        )
        if nonprofit_link and nonprofit_link.nonprofit:
            return nonprofit_link.nonprofit
        return None

    def payout_funds(self):
        if not self.created_by:
            return

        # escrow.payout() expects a Decimal object
        recipient = self.get_recipient()

        # Only payout RSC held in escrow - USD contributions are paid out separately
        payout_amount = self.escrow.amount_holding

        did_payout = self.escrow.payout(
            recipient=recipient,
            payout_amount=payout_amount,
        )

        return did_payout
