from django.core.management.base import BaseCommand

from hub.constants import CATEGORY_ORDER
from hub.models import HubCategory


class Command(BaseCommand):
    def handle(self, *args, **options):
        for category_name in CATEGORY_ORDER:
            if HubCategory.objects.filter(category_name=category_name).exists():
                continue

            category = HubCategory(category_name=category_name)

            category.save()
