import time
from decimal import Decimal

from purchase.related_models.balance_model import Balance
from reputation.distributions import create_promotional_credit_distribution
from reputation.distributor import Distributor
from reputation.related_models.distribution import Distribution
from user.related_models.user_model import User


class PromotionalFundsService:
    """
    Grants promotional funds: RSC that cannot be withdrawn (locked) but earns
    staking yield like unlocked balance.
    """

    def grant(
        self,
        user: User,
        amount: Decimal,
        *,
        reason: str,
        giver: User | None = None,
    ) -> Distribution:
        """
        Grant ``amount`` RSC of promotional funds to ``user``.

        Returns the created ``Distribution`` record (its ``Balance`` row is
        created with ``is_locked=True, lock_type=PROMOTIONAL``).
        """
        amount = Decimal(str(amount))
        if amount <= 0:
            raise ValueError("Promotional grant amount must be positive")
        reason = (reason or "").strip()
        if not reason:
            raise ValueError("Promotional grants require a reason")

        timestamp = time.time()
        distribution = create_promotional_credit_distribution(amount)
        distributor = Distributor(
            distribution,
            user,
            None,
            timestamp,
            giver=giver,
            lock_type=Balance.LockType.PROMOTIONAL,
        )
        # There is no triggering db record; the proof documents the campaign
        # or grant reason for auditability instead.
        distributor.proof = {"timestamp": timestamp, "reason": reason}
        return distributor.distribute_locked_balance()
