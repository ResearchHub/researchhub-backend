from django.core.management.base import BaseCommand
from django.db import connection

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
        parser.add_argument(
            "--remove-quotes",
            action="store_true",
            help="Remove quotation marks from headlines that are wrapped in quotes",
        )

    def handle(self, *args, **options):
        start_id = options["start_id"]
        batch_size = options["batch_size"]
        analyze_only = options["analyze"]
        remove_quotes = options["remove_quotes"]

        authors = Author.objects.filter(
            id__gt=start_id, headline__isnull=False
        ).order_by("id")

        total = authors.count()
        self.stdout.write(f"Found {total} authors with headlines to process")

        if analyze_only:
            self._analyze_headlines(authors, check_quotes=remove_quotes)
            return

        if remove_quotes:
            self._remove_quotes_from_headlines(authors, batch_size, start_id)
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

    def _remove_quotes_from_headlines(self, authors, batch_size, start_id):
        """Remove quotation marks from headlines that are wrapped in quotes."""
        self.stdout.write("=== Removing Quotation Marks from Headlines ===")

        # Check if the column is JSONB or TEXT
        column_type = self._get_headline_column_type()
        self.stdout.write(f"Column type detected: {column_type}")

        if column_type == "jsonb":
            self._remove_quotes_jsonb(authors, batch_size, start_id)
        else:
            self._remove_quotes_text(authors, batch_size, start_id)

    def _get_headline_column_type(self):
        """Check if the headline column is JSONB or TEXT."""
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT data_type
                FROM information_schema.columns
                WHERE table_name = 'user_author'
                AND column_name = 'headline'
                """
            )
            result = cursor.fetchone()
            return result[0] if result else "text"

    def _remove_quotes_jsonb(self, authors, batch_size, start_id):
        """Remove quotes from JSONB headlines using raw SQL with proper casting."""
        self.stdout.write("Using JSONB-compatible update method...")

        fixed_count = 0
        last_id = start_id
        ids_to_update = []

        for author in authors.iterator(chunk_size=batch_size):
            last_id = author.id
            headline = author.headline

            if isinstance(headline, str):
                # Check if headline is wrapped in quotes
                stripped = headline.strip()
                if (stripped.startswith('"') and stripped.endswith('"')) or (
                    stripped.startswith("'") and stripped.endswith("'")
                ):
                    ids_to_update.append(author.id)
                    fixed_count += 1

            if len(ids_to_update) >= batch_size:
                self._update_jsonb_headlines(ids_to_update)
                self.stdout.write(f"Updated batch. Last ID: {last_id}")
                ids_to_update = []

        if ids_to_update:
            self._update_jsonb_headlines(ids_to_update)

        self.stdout.write(
            self.style.SUCCESS(f"Removed quotes from {fixed_count} author headlines")
        )

    def _update_jsonb_headlines(self, author_ids):
        """Update JSONB headlines using raw SQL to strip outer quotes."""
        with connection.cursor() as cursor:
            # Use JSONB operations to strip quotes:
            # headline #>> '{}' extracts the text value from JSONB
            # Then we cast it back to JSONB with to_jsonb()
            # Note: '{}' in PostgreSQL JSONB means extract the top-level value
            sql = """
                UPDATE user_author
                SET headline = to_jsonb(
                    CASE
                        WHEN (headline #>> '{}') ~ '^".*"$'
                        THEN substring(
                            headline #>> '{}' from 2
                            for length(headline #>> '{}') - 2
                        )
                        WHEN (headline #>> '{}') ~ '^''.*''$'
                        THEN substring(
                            headline #>> '{}' from 2
                            for length(headline #>> '{}') - 2
                        )
                        ELSE headline #>> '{}'
                    END
                )
                WHERE id = ANY(%s)
                """
            cursor.execute(sql, [author_ids])

    def _remove_quotes_text(self, authors, batch_size, start_id):
        """Remove quotes from TEXT headlines using Django ORM."""
        self.stdout.write("Using TEXT-compatible update method...")

        updated_authors = []
        fixed_count = 0
        last_id = start_id

        for author in authors.iterator(chunk_size=batch_size):
            last_id = author.id
            headline = author.headline

            if isinstance(headline, str):
                # Check if headline is wrapped in quotes
                stripped = headline.strip()
                if (stripped.startswith('"') and stripped.endswith('"')) or (
                    stripped.startswith("'") and stripped.endswith("'")
                ):
                    # Remove the outer quotes
                    author.headline = stripped[1:-1]
                    updated_authors.append(author)
                    fixed_count += 1

            if len(updated_authors) >= batch_size:
                Author.objects.bulk_update(updated_authors, ["headline"])
                self.stdout.write(f"Updated batch. Last ID: {last_id}")
                updated_authors = []

        if updated_authors:
            Author.objects.bulk_update(updated_authors, ["headline"])

        self.stdout.write(
            self.style.SUCCESS(f"Removed quotes from {fixed_count} author headlines")
        )

    def _analyze_headlines(self, authors, check_quotes=False):
        """Analyze the current state of headline data."""
        self.stdout.write("=== Analyzing Headline Data ===")

        string_count = 0
        object_count = 0
        null_count = 0
        other_count = 0
        quoted_count = 0

        for author in authors.iterator():
            headline = author.headline
            if isinstance(headline, str):
                string_count += 1
                if check_quotes:
                    stripped = headline.strip()
                    if (stripped.startswith('"') and stripped.endswith('"')) or (
                        stripped.startswith("'") and stripped.endswith("'")
                    ):
                        quoted_count += 1
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

        if check_quotes:
            self.stdout.write(f"  Quoted headlines: {quoted_count}")
            if quoted_count > 0:
                self.stdout.write(
                    self.style.WARNING(
                        f"Found {quoted_count} authors with quoted headlines that need fixing"  # noqa: E501
                    )
                )
            else:
                self.stdout.write(
                    self.style.SUCCESS("No headlines are wrapped in quotes")
                )

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
