from django.db import transaction

from reputation.related_models.hot_wallet_nonce import HotWalletNonce


class HotWalletNonceService:
    """
    Hands out hot-wallet broadcast nonces so two withdrawals never share one.
    See HotWalletNonce for why reserved nonces are never handed back.
    """

    def reserve_withdrawal_nonce(self, withdrawal, sender, chain_nonce):
        """
        Lock the counter for the withdrawal's network and sender, then assign
        max(counter, chain_nonce) to the withdrawal and advance the counter in
        the same transaction. chain_nonce is the sender's pending transaction
        count, so the counter catches up with transactions sent elsewhere.
        """
        with transaction.atomic():
            counter, _ = HotWalletNonce.objects.select_for_update().get_or_create(
                network=withdrawal.network, address=sender
            )
            withdrawal.broadcast_nonce = max(counter.next_nonce, chain_nonce)
            withdrawal.save(update_fields=["broadcast_nonce"])
            counter.next_nonce = withdrawal.broadcast_nonce + 1
            counter.save(update_fields=["next_nonce", "updated_date"])
        return withdrawal
