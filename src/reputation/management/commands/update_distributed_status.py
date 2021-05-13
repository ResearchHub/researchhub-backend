'''
Set all distribution statuses to so they are eligible for withdrawal.
'''
from django.core.management.base import BaseCommand

from reputation.models import Distribution


class Command(BaseCommand):

    def handle(self, *args, **options):
        old_distribued = Distribution.objects.filter(
            distributed_status='distributed'
        )
        for distribution in old_distribued:
            try:
                distribution.distributed_status = Distribution.DISTRIBUTED
                distribution.save()
                self.stdout.write(self.style.SUCCESS(
                    f'Updated distribution {distribution.id}'
                ))
            except Exception as e:
                self.stdout.write(self.style.ERROR(
                    f'Failed to update distribution {distribution.id}: {e}'
                ))

        undistributed = Distribution.objects.filter(distributed_status=None)
        for distribution in undistributed:
            try:
                distribution.set_distributed()
                self.stdout.write(self.style.SUCCESS(
                    f'Updated distribution {distribution.id}'
                ))
            except Exception as e:
                self.stdout.write(self.style.ERROR(
                    f'Failed to update distribution {distribution.id}: {e}'
                ))

        self.stdout.write(self.style.SUCCESS(f'Done updating distributions'))
