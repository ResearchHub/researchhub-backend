from decimal import Decimal

from django.db import transaction

from reputation.distributions import Distribution
from reputation.distributor import Distributor
from user.models import User


class BalancePenaltyService:
    """Apply an unlocked-balance penalty without allowing an overdraft."""

    def __init__(self, distributor_class=Distributor) -> None:
        self.distributor_class = distributor_class

    @transaction.atomic
    def apply(
        self,
        *,
        user: User,
        penalty: Distribution,
        db_record,
        timestamp: float,
        giver: User | None = None,
        hubs=None,
    ):
        user = User.objects.select_for_update().get(pk=user.pk)
        configured_amount = Decimal(str(penalty.amount))
        if not configured_amount.is_finite() or configured_amount > 0:
            raise ValueError("Balance penalties must be finite and non-positive")

        available_balance = max(user.get_available_balance(), Decimal(0))
        charged_amount = min(-configured_amount, available_balance)
        capped_penalty = Distribution(
            penalty.name,
            -charged_amount,
            give_rep=penalty.gives_rep,
            reputation=penalty.reputation,
        )
        distributor = self.distributor_class(
            capped_penalty,
            user,
            db_record,
            timestamp,
            giver,
            hubs,
        )
        return distributor.distribute()
