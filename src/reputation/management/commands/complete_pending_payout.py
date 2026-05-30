from django.core.management.base import BaseCommand

from reputation.models import Withdrawal
from reputation.tasks import broadcast_withdrawal


class Command(BaseCommand):
    def handle(self, *args, **options):
        withdrawals_to_complete = [1868, 1864]
        withdrawals = Withdrawal.objects.filter(
            id__in=withdrawals_to_complete, paid_status="PENDING"
        )
        for withdrawal in withdrawals:
            broadcast_withdrawal.delay(withdrawal.id)
