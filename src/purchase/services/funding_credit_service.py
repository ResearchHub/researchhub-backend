from decimal import Decimal
from typing import Optional

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Sum
from django.db.models.functions import Coalesce

from purchase.models import Fundraise, FundingCredit
from user.models import User


class FundingCreditService:
    """
    Service for managing funding credit operations.

    Funding credits are non-liquid rewards earned from staking RSC.
    They can ONLY be spent on funding research proposals (fundraises).
    """

    def get_user_balance(self, user: User) -> Decimal:
        """
        Returns the total funding credit balance for a user.

        Args:
            user: The user to get balance for

        Returns:
            Total funding credit balance
        """
        return user.funding_credits.aggregate(
            total=Coalesce(Sum("amount"), Decimal("0"))
        )["total"]

    def add_credits(
        self,
        user: User,
        amount: Decimal,
        source=None,
        credit_type: str = FundingCredit.CreditType.STAKING_REWARD,
    ) -> FundingCredit:
        """
        Adds funding credits to a user's account.

        Args:
            user: The user to add credits to
            amount: The amount to add (must be positive)
            source: Optional source object to track the origin
            credit_type: Type of credit (default: STAKING_REWARD)

        Returns:
            Created FundingCredit record

        Raises:
            ValueError: If amount is not positive
        """
        if amount <= 0:
            raise ValueError("Amount must be positive")

        content_type = None
        object_id = None

        if source is not None:
            content_type = ContentType.objects.get_for_model(source)
            object_id = source.id

        return FundingCredit.objects.create(
            user=user,
            amount=amount,
            credit_type=credit_type,
            content_type=content_type,
            object_id=object_id,
        )

    def spend_credits(
        self,
        user: User,
        amount: Decimal,
        fundraise: Fundraise,
    ) -> tuple[Optional[FundingCredit], Optional[str]]:
        """
        Spends funding credits on a fundraise contribution.

        Args:
            user: The user spending credits
            amount: The amount to spend (must be positive)
            fundraise: The fundraise to contribute to

        Returns:
            Tuple of (FundingCredit, error_message)
            If successful, error_message is None.
            If failed, FundingCredit is None and error_message contains the reason.
        """
        if amount <= 0:
            return None, "Amount must be positive"

        with transaction.atomic():
            # Get current balance
            current_balance = self.get_user_balance(user)

            if current_balance < amount:
                return None, "Insufficient funding credit balance"

            # Create negative credit record (debit)
            content_type = ContentType.objects.get_for_model(fundraise)

            credit = FundingCredit.objects.create(
                user=user,
                amount=-amount,  # Negative for spending
                credit_type=FundingCredit.CreditType.FUNDRAISE_CONTRIBUTION,
                content_type=content_type,
                object_id=fundraise.id,
            )

            return credit, None

    def get_recent_transactions(
        self,
        user: User,
        limit: int = 20,
    ) -> list[FundingCredit]:
        """
        Returns recent funding credit transactions for a user.

        Args:
            user: The user to get transactions for
            limit: Maximum number of transactions to return

        Returns:
            List of FundingCredit records
        """
        return list(
            user.funding_credits.order_by("-created_date")[:limit]
        )
