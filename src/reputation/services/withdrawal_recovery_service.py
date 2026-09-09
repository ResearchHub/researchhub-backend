import logging
from datetime import timedelta

from django.core.cache import cache
from django.db import transaction
from django.db.models import Q
from django.db.models.functions import Coalesce
from django.utils import timezone

from reputation.models import Withdrawal
from reputation.related_models.paid_status_mixin import PaidStatusModelMixin

logger = logging.getLogger(__name__)


class WithdrawalRecoveryService:
    def __init__(
        self, *, evaluate_receipt=None, enqueue_broadcast=None, alert_cache=None
    ):
        # Deferred imports avoid the lib/tasks/service import cycle.
        if evaluate_receipt is None:
            from reputation.lib import evaluate_transaction_hash

            evaluate_receipt = evaluate_transaction_hash
        if enqueue_broadcast is None:
            from reputation.tasks import broadcast_withdrawal

            enqueue_broadcast = broadcast_withdrawal.delay
        self.evaluate_receipt = evaluate_receipt
        self.enqueue_broadcast = enqueue_broadcast
        self.alert_cache = alert_cache if alert_cache is not None else cache

    def check_pending(self):
        # Only operations with no evidence of submission can be auto-retried.
        unsubmitted = Withdrawal.objects.filter(
            paid_status__in=[
                PaidStatusModelMixin.INITIATED,
                PaidStatusModelMixin.PENDING,
            ],
            broadcast_nonce__isnull=True,
            nonce_reservation__isnull=True,
        ).filter(Q(transaction_hash__isnull=True) | Q(transaction_hash=""))
        for withdrawal in unsubmitted.iterator():
            self.enqueue_broadcast(withdrawal.id)

        pending = Withdrawal.objects.filter(
            paid_status=PaidStatusModelMixin.PENDING,
            transaction_hash__isnull=False,
        ).exclude(transaction_hash="")
        for withdrawal_id in pending.values_list("id", flat=True).iterator():
            with transaction.atomic():
                withdrawal = Withdrawal.objects.select_for_update().get(
                    id=withdrawal_id
                )
                # The initial list may predate a manual correction or another worker.
                if (
                    withdrawal.paid_status != PaidStatusModelMixin.PENDING
                    or not withdrawal.transaction_hash
                ):
                    continue
                paid_status, paid_date = self.evaluate_receipt(
                    withdrawal.transaction_hash, network=withdrawal.network
                )
                if paid_status != PaidStatusModelMixin.PENDING:
                    withdrawal.paid_status = paid_status
                    withdrawal.paid_date = paid_date
                    withdrawal.save(
                        update_fields=["paid_status", "paid_date", "updated_date"]
                    )

        stale = (
            Withdrawal.objects.filter(
                paid_status__in=[
                    PaidStatusModelMixin.INITIATED,
                    PaidStatusModelMixin.PENDING,
                ]
            )
            .annotate(
                pending_since=Coalesce(
                    "nonce_reservation__created_date", "created_date"
                )
            )
            .filter(pending_since__lt=timezone.now() - timedelta(minutes=10))
        )
        for withdrawal in stale.iterator():
            # Error logs are captured by the existing production Sentry integration.
            # Repeat at most hourly per withdrawal while it remains unresolved.
            if self.alert_cache.add(
                f"stale-withdrawal:{withdrawal.id}", True, timeout=3600
            ):
                logger.error(
                    "Withdrawal pending over 10 minutes; manual review required: "
                    "withdrawal=%s network=%s nonce=%s hash=%s pending_since=%s",
                    withdrawal.id,
                    withdrawal.network,
                    withdrawal.broadcast_nonce,
                    withdrawal.transaction_hash,
                    withdrawal.pending_since,
                )
