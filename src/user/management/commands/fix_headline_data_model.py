from django.core.management.base import BaseCommand

from user.models import Author


class Command(BaseCommand):
    help = "Fix Author headline field from object format to string format"

    def add_arguments(self, parser):
        parser.add_argument(
            "--start-id",
            type=int,
            default=0,
            help="Start processing from this Author ID (useful for resuming)",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=100,
            help="Number of records to update in each batch",
        )

    def handle(self, *args, **options):
        start_id = options["start_id"]
        batch_size = options["batch_size"]

        authors = Author.objects.filter(
            id__gt=start_id, headline__isnull=False
        ).order_by("id")

        total = authors.count()
        self.stdout.write(f"Found {total} authors with headlines to process")

        updated_authors = []
        fixed_count = 0
        last_id = start_id

        for author in authors.iterator(chunk_size=batch_size):
            last_id = author.id
            headline = author.headline

            if isinstance(headline, dict):
                author.headline = headline.get("title", "")
                updated_authors.append(author)
                fixed_count += 1

            if len(updated_authors) >= batch_size:
                Author.objects.bulk_update(updated_authors, ["headline"])
                self.stdout.write(f"Updated batch. Last ID: {last_id}")
                updated_authors = []

        if updated_authors:
            Author.objects.bulk_update(updated_authors, ["headline"])

        self.stdout.write(self.style.SUCCESS(f"Fixed {fixed_count} author headlines"))
