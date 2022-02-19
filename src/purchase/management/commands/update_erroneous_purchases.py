from django.core.management.base import BaseCommand
from django.contrib.contenttypes.models import ContentType

from purchase.models import Purchase, Balance


class Command(BaseCommand):
    # Updates purchases and the corresponding balance to 0

    def handle(self, *args, **options):
        purchases = Purchase.objects.filter(amount__icontains='-')
        purchase_ids = purchases.values_list('id', flat=True)
        purchase_content_type = ContentType.objects.get_for_model(Purchase)

        for purchase in purchases.iterator():
            print(purchase.amount)
            purchase.amount = '0'
            purchase.save()

        balances = Balance.objects.filter(
            content_type=purchase_content_type,
            object_id__in=purchase_ids
        )
        for balance in balances.iterator():
            balance.amount = '0'
            balance.save()
