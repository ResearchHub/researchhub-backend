from django.core.management.base import BaseCommand

from hub.models import Hub


class Command(BaseCommand):
    """
    One-off command to update all hub names to title case
    (e.g., from 'computer science' to 'Computer Science').
    """

    def handle(self, *args, **options):
        hubs = Hub.objects.all()
        for hub in hubs:
            title = hub.name.title()
            if hub.name != title:
                print(f"Updating hub name '{hub.name}' to '{title}' (id: {hub.id})")
                hub.name = hub.name.title()
                hub.save()
