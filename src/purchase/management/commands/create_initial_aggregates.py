'''
Creates aggregate groups for initial purchases
'''

from django.core.management.base import BaseCommand

from purchase.models import Purchase


class Command(BaseCommand):

    def handle(self, *args, **options):
        purchases = Purchase.objects.filter(group=None)
        purchases_count = purchases.count()
        for i, purchase in enumerate(purchases.iterator()):
            print(f'{i + 1}/{purchases_count}')
            purchase.group = purchase.get_aggregate_group()
            purchase.save()
