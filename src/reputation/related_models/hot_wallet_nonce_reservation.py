from django.db import models
from django.db.models.functions import Lower


class HotWalletNonceReservation(models.Model):
    """Permanent record of a nonce that may have been submitted to the network."""

    chain_id = models.PositiveBigIntegerField()
    sender = models.CharField(max_length=42)
    nonce = models.PositiveBigIntegerField()
    withdrawal = models.OneToOneField(
        "reputation.Withdrawal",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="nonce_reservation",
    )
    created_date = models.DateTimeField(auto_now_add=True)
    to_address = models.CharField(max_length=42)
    amount = models.CharField(max_length=255)
    transaction_hash = models.CharField(max_length=255, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                "chain_id", Lower("sender"), "nonce", name="unique_hot_wallet_nonce"
            )
        ]
