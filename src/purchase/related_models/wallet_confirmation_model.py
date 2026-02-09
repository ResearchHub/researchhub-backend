from django.db import models


class WalletConfirmation(models.Model):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    STATUS_CHOICES = [
        (PENDING, "Pending"),
        (CONFIRMED, "Confirmed"),
    ]

    user = models.ForeignKey(
        "user.User", on_delete=models.CASCADE, related_name="confirmed_wallets"
    )
    address = models.CharField(max_length=255)  # checksummed ethereum address
    nonce = models.CharField(max_length=64)  # challenge nonce
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["address"],
                condition=models.Q(status="CONFIRMED"),
                name="unique_confirmed_address",
            )
        ]

    def __str__(self):
        return f"{self.address} ({self.status})"
