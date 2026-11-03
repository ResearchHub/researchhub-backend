from django.db import models

from utils.models import DefaultModel


class HotWalletNonce(DefaultModel):
    """
    Next broadcast nonce to hand out for a hot wallet on a network. Withdrawals
    reserve nonces by locking this row, so two of them never share one.

    A reserved nonce is never handed back. A withdrawal keeps its nonce across
    retries, and is parked for manual reconciliation when retries run out, so
    the nonce may already be on chain. Handing it to another withdrawal could
    pay twice. If a parked withdrawal's nonce turns out to be unused, every
    later nonce stays queued behind it until that gap is filled. To fill it,
    re-broadcast the withdrawal at its own nonce (set it back to INITIATED and
    keep broadcast_nonce), or send a zero-value transaction at that nonce
    before refunding it.
    """

    network = models.CharField(
        max_length=10,
        choices=[("BASE", "Base"), ("ETHEREUM", "Ethereum")],
    )
    address = models.CharField(max_length=42)
    next_nonce = models.PositiveBigIntegerField(default=0)

    class Meta:
        app_label = "reputation"
        constraints = [
            models.UniqueConstraint(
                fields=["network", "address"],
                name="unique_hot_wallet_nonce_network_address",
            )
        ]

    def __str__(self):
        return f"HotWalletNonce({self.network}, {self.address}, {self.next_nonce})"
