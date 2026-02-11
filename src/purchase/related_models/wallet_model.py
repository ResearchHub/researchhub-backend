from django.db import models


class Wallet(models.Model):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    STATUS_CHOICES = [(PENDING, "Pending"), (CONFIRMED, "Confirmed")]

    EXTERNAL = "EXTERNAL"
    CDP_EMBEDDED = "CDP_EMBEDDED"
    WALLET_TYPE_CHOICES = [(EXTERNAL, "External"), (CDP_EMBEDDED, "CDP Embedded")]

    user = models.ForeignKey(
        "user.User", on_delete=models.CASCADE, related_name="wallets"
    )
    address = models.CharField(max_length=255, db_index=True)
    nonce = models.CharField(max_length=64, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING)
    wallet_type = models.CharField(
        max_length=20, choices=WALLET_TYPE_CHOICES, default=EXTERNAL
    )
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
