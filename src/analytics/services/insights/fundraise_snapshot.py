from decimal import Decimal

from django.db.models import DecimalField, Sum
from django.db.models.functions import Coalesce

from purchase.models import Fundraise

AMOUNT_FIELD = DecimalField(max_digits=19, decimal_places=10)


def get_fundraise_snapshot(period):
    """Return fundraise holding and distribution totals for the report period."""
    totals = Fundraise.objects.filter(
        created_date__gte=period.start,
        created_date__lt=period.end,
    ).aggregate(
        holding_rsc=Coalesce(
            Sum("escrow__amount_holding"),
            Decimal(0),
            output_field=AMOUNT_FIELD,
        ),
        distributed_rsc=Coalesce(
            Sum("escrow__amount_paid"),
            Decimal(0),
            output_field=AMOUNT_FIELD,
        ),
    )

    return {
        "holding_rsc": round(totals["holding_rsc"], 2),
        "distributed_rsc": round(totals["distributed_rsc"], 2),
    }
