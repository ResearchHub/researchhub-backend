'''
Removes all unpaid distributions so they will not be eligible for withdrawal.
'''
from django.core.management.base import BaseCommand

from purchase.models import Balance

class Command(BaseCommand):

    def handle(self, *args, **options):
        balances = Balance.objects.all()
        for balance in balances:
            try:
                balance.testnet_amount = balance.amount
                balance.amount = 0
                balance.save()
                self.stdout.write(self.style.SUCCESS(
                    f'Removed balance {balance.id}'
                ))
            except Exception as e:
                self.stdout.write(self.style.ERROR(
                    f'Failed to remove balance {balance.id}: {e}'
                ))

        self.stdout.write(self.style.SUCCESS(f'Done wiping balances'))
