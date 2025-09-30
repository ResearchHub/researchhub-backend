"""
Find duplicate hubs based on case-insensitive name matching.
"""

from django.core.management.base import BaseCommand
from django.db.models import Count
from django.db.models.functions import Lower

from hub.models import Hub


class Command(BaseCommand):
    help = "Identify duplicate hubs based on case-insensitive name matching"

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("Finding duplicate hubs..."))
        self.stdout.write("")

        # Find all hubs grouped by lowercase name, with duplicates
        duplicates = (
            Hub.objects.filter(is_removed=False)
            .values(lower_name=Lower("name"))
            .annotate(count=Count("id"))
            .filter(count__gt=1)
            .order_by("-count", "lower_name")
        )

        total_duplicate_groups = duplicates.count()

        if total_duplicate_groups == 0:
            self.stdout.write(self.style.SUCCESS("No duplicate hubs found!"))
            return

        self.stdout.write(
            self.style.WARNING(
                f"Found {total_duplicate_groups} groups of duplicate hubs\n"
            )
        )

        # For each duplicate group, show all hubs with that name
        for dup_group in duplicates:
            lower_name = dup_group["lower_name"]
            count = dup_group["count"]

            # Get all hubs with this name (case-insensitive)
            hubs_in_group = Hub.objects.filter(
                name__iexact=lower_name, is_removed=False
            ).order_by("id")

            self.stdout.write("=" * 80)
            self.stdout.write(
                self.style.WARNING(
                    f'\nDuplicate Group: "{lower_name}" ({count} hubs)\n'
                )
            )

            for hub in hubs_in_group:
                self.stdout.write(f"  ID: {hub.id}")
                self.stdout.write(f"  Name: {hub.name}")
                self.stdout.write(f"  Namespace: {hub.namespace or 'None'}")
                self.stdout.write(f"  Paper Count: {hub.paper_count}")
                self.stdout.write(f"  Subscriber Count: {hub.subscriber_count}")
                self.stdout.write(f"  Slug: {hub.slug}")
                self.stdout.write(f"  Created: {hub.created_date}")
                self.stdout.write("")

        self.stdout.write("=" * 80)
        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Summary: Found {total_duplicate_groups} groups with duplicate names"
            )
        )
