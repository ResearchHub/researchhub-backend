from django.core.management.base import BaseCommand
from purchase.models import Balance
from reputation.lib import (
    PendingWithdrawal
)
from reputation.models import Withdrawal
from django.contrib.contenttypes.models import ContentType

class Command(BaseCommand):

    def handle(self, *args, **options):
        withdrawals_to_complete = [1868, 1864]
        withdrawals = Withdrawal.objects.filter(id__in=withdrawals_to_complete, paid_status="PENDING")
        for withdrawal in withdrawals:
            source_type = ContentType.objects.get_for_model(withdrawal)
            ending_balance_record = Balance.objects.get(
                object_id=withdrawal.id,
                content_type=source_type
            )
            amount = withdrawal.amount
            pending_withdrawal = PendingWithdrawal(
                withdrawal,
                ending_balance_record.id,
                int(amount)
            )
            pending_withdrawal.complete_token_transfer()
