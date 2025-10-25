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
        parser.add_argument(
            "--analyze",
            action="store_true",
            help="Only analyze the data, don't make changes",
        )

    def handle(self, *args, **options):
        start_id = options["start_id"]
        batch_size = options["batch_size"]
        analyze_only = options["analyze"]

        authors = Author.objects.filter(
            id__gt=start_id, headline__isnull=False
        ).order_by("id")

        total = authors.count()
        self.stdout.write(f"Found {total} authors with headlines to process")

        if analyze_only:
            self._analyze_headlines(authors)
            return

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

    def _analyze_headlines(self, authors):
        """Analyze the current state of headline data."""
        self.stdout.write("=== Analyzing Headline Data ===")

        string_count = 0
        object_count = 0
        null_count = 0
        other_count = 0

        for author in authors.iterator():
            headline = author.headline
            if isinstance(headline, str):
                string_count += 1
            elif isinstance(headline, dict):
                object_count += 1
            elif headline is None:
                null_count += 1
            else:
                other_count += 1

        self.stdout.write(f"  String headlines: {string_count}")
        self.stdout.write(f"  Object headlines: {object_count}")
        self.stdout.write(f"  Null headlines: {null_count}")
        self.stdout.write(f"  Other types: {other_count}")

        if object_count > 0:
            self.stdout.write(
                self.style.WARNING(
                    f"Found {object_count} authors with object headlines that need fixing"  # noqa: E501
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS("All headlines are already in string format")
            )
