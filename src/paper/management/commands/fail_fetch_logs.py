from django.core.management.base import BaseCommand

from paper.models import PaperFetchLog


class Command(BaseCommand):
    help = "Mark lingering paper fetch logs as failed for a specific journal"

    def add_arguments(self, parser):
        parser.add_argument("journal", type=str, help="Journal to mark logs for")

    def handle(self, *args, **options):
        journal = options["journal"]

        self.stdout.write(f"Checking pending logs for {journal}")

        pending_logs = PaperFetchLog.objects.filter(
            source=PaperFetchLog.OPENALEX, status=PaperFetchLog.PENDING, journal=journal
        )

        count = pending_logs.count()

        if not count:
            self.stdout.write(self.style.WARNING("None found"))

            return

        pending_logs.update(status=PaperFetchLog.FAILED)

        self.stdout.write(self.style.SUCCESS(f"Marked {count} logs as failed"))
