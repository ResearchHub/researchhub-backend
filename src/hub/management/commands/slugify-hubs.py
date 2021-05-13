from django.core.management.base import BaseCommand
from hub.models import Hub
import os

class Command(BaseCommand):
    def handle(self, *args, **options):
        all_hubs = Hub.objects.all()
        for hub in all_hubs:
            slug = hub.slugify()
            hub.save()
            print(slug)