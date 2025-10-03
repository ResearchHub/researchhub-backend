from django.core.management.base import BaseCommand

from feed.tasks import _refresh_feed


class Command(BaseCommand):
    help = "Refresh the materialized feed views"

    def handle(self, *args, **options):
        self.stdout.write("Refreshing materialized feed views...")

        try:
            _refresh_feed()

            self.stdout.write(
                self.style.SUCCESS("Successfully refreshed feed materialized views!")
            )

        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"Failed to refresh feed materialized views:\n{e}")
            )

            raise
