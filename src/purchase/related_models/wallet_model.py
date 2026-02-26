from django.db import models

# Map deposit network values to the Wallet model field that stores
# the Circle wallet ID for that chain.
NETWORK_TO_WALLET_FIELD = {
    "ETHEREUM": "circle_wallet_id",
    "BASE": "circle_base_wallet_id",
}


class Wallet(models.Model):
    WALLET_TYPE_EXTERNAL = "EXTERNAL"
    WALLET_TYPE_CIRCLE = "CIRCLE"
    WALLET_TYPE_CHOICES = [
        (WALLET_TYPE_EXTERNAL, "External"),
        (WALLET_TYPE_CIRCLE, "Circle"),
    ]

    user = models.OneToOneField(
        "user.User",
        related_name="wallet",
        on_delete=models.CASCADE,
    )
    address = models.CharField(max_length=255, null=True)

    circle_wallet_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        unique=True,
        help_text="Circle wallet ID for the Ethereum chain.",
    )
    circle_base_wallet_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        unique=True,
        help_text="Circle wallet ID for the Base chain.",
    )
    wallet_type = models.CharField(
        max_length=20,
        choices=WALLET_TYPE_CHOICES,
        default=WALLET_TYPE_EXTERNAL,
    )

    @classmethod
    def get_by_circle_wallet_id(cls, circle_wallet_id: str, network: str):
        """
        Look up a Wallet by a Circle wallet ID.

        *network* must be ``"ETHEREUM"`` or ``"BASE"``; only the
        corresponding field is checked — a single unique-index hit.
        """
        field = NETWORK_TO_WALLET_FIELD.get(network)
        if not field:
            raise ValueError(f"Unsupported network: {network!r}")
        return cls.objects.select_related("user").get(**{field: circle_wallet_id})

    def get_circle_wallet_id_for_network(self, network: str) -> str | None:
        """Return the Circle wallet ID for the given deposit network."""
        field = NETWORK_TO_WALLET_FIELD.get(network)
        return getattr(self, field) if field else None
