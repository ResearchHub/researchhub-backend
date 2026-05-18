from purchase.models import Wallet
from reputation.models import Deposit


class DepositService:
    """Ownership checks for on-chain RSC deposits."""

    @staticmethod
    def normalize_address(address: str) -> str:
        if not address:
            return ""
        return address.strip().lower()

    @classmethod
    def get_user_linked_from_addresses(cls, user) -> set[str]:
        """
        Return on-chain sender addresses linked to the user.

        Addresses are linked via the user's Circle wallet record or prior paid
        deposits.
        """
        addresses: set[str] = set()

        try:
            wallet = Wallet.objects.get(user=user)
            if wallet.address:
                addresses.add(cls.normalize_address(wallet.address))
        except Wallet.DoesNotExist:
            pass

        paid_from_addresses = (
            Deposit.objects.filter(user=user, paid_status=Deposit.PAID)
            .exclude(from_address="")
            .values_list("from_address", flat=True)
        )
        for address in paid_from_addresses:
            addresses.add(cls.normalize_address(address))

        return addresses

    @classmethod
    def is_from_address_linked_to_another_user(cls, from_address: str, user) -> bool:
        normalized = cls.normalize_address(from_address)
        if not normalized:
            return False

        if (
            Wallet.objects.filter(address__iexact=from_address)
            .exclude(user=user)
            .exists()
        ):
            return True

        return (
            Deposit.objects.filter(
                from_address__iexact=from_address,
                paid_status=Deposit.PAID,
            )
            .exclude(user=user)
            .exists()
        )

    @classmethod
    def user_owns_from_address(cls, user, from_address: str) -> bool:
        """
        Return True when the user may claim credit for deposits from
        ``from_address``.

        The address must either already be linked to the user, or not be linked
        to any other account (first-time deposit from a new external wallet).
        """
        normalized = cls.normalize_address(from_address)
        if not normalized:
            return False

        if normalized in cls.get_user_linked_from_addresses(user):
            return True

        return not cls.is_from_address_linked_to_another_user(from_address, user)
