from decimal import Decimal

from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate


class FundingActivityAmountsService:
    """Rate resolution and RSC/USD dual-amount helpers for FundingActivity."""

    @classmethod
    def get_historical_rsc_usd_rate(cls, at_datetime) -> float | None:
        """Return Coalesce(real_rate, rate) for the latest USD rate at or before at_datetime."""
        rate_record = (
            RscExchangeRate.objects.filter(
                created_date__lte=at_datetime,
                target_currency="USD",
            )
            .order_by("-created_date")
            .first()
        )
        if rate_record is None:
            return None
        return (
            rate_record.real_rate
            if rate_record.real_rate is not None
            else rate_record.rate
        )

    @classmethod
    def resolve_rate_for_purchase(cls, purchase) -> float | None:
        """Prefer purchase.rsc_usd_rate, else historical rate at purchase.created_date."""
        if purchase.rsc_usd_rate is not None:
            return purchase.rsc_usd_rate
        return cls.get_historical_rsc_usd_rate(purchase.created_date)

    @classmethod
    def rsc_to_usd_cents(cls, rsc_amount, rate) -> int:
        return round(float(rsc_amount) * rate * 100)

    @classmethod
    def usd_cents_to_rsc(cls, usd_cents, rate) -> Decimal:
        return Decimal(str(usd_cents / 100 / rate))

    @classmethod
    def populate_dual_amounts_on_recipients(
        cls, activity, recipients_data, rate
    ) -> None:
        """
        Set usd_cents on activity and each recipient from native RSC amounts and rate.
        When rate is unavailable, usd_cents remains 0.
        """
        if rate is None:
            activity.usd_cents = 0
            for recipient in recipients_data:
                recipient.usd_cents = 0
            return

        activity.usd_cents = cls.rsc_to_usd_cents(activity.total_amount, rate)
        for recipient in recipients_data:
            recipient.usd_cents = cls.rsc_to_usd_cents(recipient.amount, rate)

    @classmethod
    def populate_usd_native_dual_amounts_on_recipients(
        cls, activity, recipients_data, usd_cents, rate
    ) -> None:
        """
        Set native USD and calculated RSC on activity and recipients.
        usd_cents is always set from native USD; RSC amounts use rate when available.
        """
        activity.usd_cents = usd_cents
        for recipient in recipients_data:
            recipient.usd_cents = usd_cents

        if rate is None:
            activity.total_amount = Decimal("0")
            for recipient in recipients_data:
                recipient.amount = Decimal("0")
            return

        calculated_rsc = cls.usd_cents_to_rsc(usd_cents, rate)
        activity.total_amount = calculated_rsc
        for recipient in recipients_data:
            recipient.amount = calculated_rsc
