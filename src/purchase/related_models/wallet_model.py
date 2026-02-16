from django.db import models


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
    eth_address = models.CharField(max_length=255, null=True)
    btc_address = models.CharField(max_length=255, null=True)
    rsc_address = models.CharField(max_length=255, null=True)

    # Circle developer-controlled wallet fields
    circle_wallet_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        unique=True,
    )
    wallet_type = models.CharField(
        max_length=20,
        choices=WALLET_TYPE_CHOICES,
        default=WALLET_TYPE_EXTERNAL,
    )
