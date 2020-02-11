'''
Removes all unpaid distributions so they will not be eligible for withdrawal.
'''
from django.core.management.base import BaseCommand

from reputation.models import Distribution


class Command(BaseCommand):

    def handle(self, *args, **options):
        distributions = Distribution.objects.exclude(
            paid_status=Distribution.PAID
        )
        for distribution in distributions:
            try:
                distribution.delete(soft=True)
                self.stdout.write(self.style.SUCCESS(
                    f'Removed distribution {distribution.id}'
                ))
            except Exception as e:
                self.stdout.write(self.style.ERROR(
                    f'Failed to remove distribution {distribution.id}: {e}'
                ))

        self.stdout.write(self.style.SUCCESS(f'Done wiping balances'))
