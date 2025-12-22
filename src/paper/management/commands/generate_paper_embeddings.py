"""
Management command to generate vector embeddings for papers using AWS Bedrock.
"""

from dateutil import parser
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from paper.models import Paper
from paper.tasks import generate_embeddings_batch, generate_paper_embedding


class Command(BaseCommand):
    help = "Generate vector embeddings for papers using AWS Bedrock Titan"

    def add_arguments(self, parser):
        parser.add_argument(
            "paper_id",
            type=int,
            nargs="*",
            help="Paper ID(s) to generate embeddings for (can specify multiple)",
        )
        # Published date range
        parser.add_argument(
            "--published-start",
            help="Filter by published date starting from (paper_publish_date)",
        )
        parser.add_argument(
            "--published-end",
            help="Filter by published date ending at (defaults to today)",
        )
        # Created date range
        parser.add_argument(
            "--created-start",
            help="Filter by created date starting from",
        )
        parser.add_argument(
            "--created-end",
            help="Filter by created date ending at (defaults to today)",
        )
        # Options
        parser.add_argument(
            "--async",
            action="store_true",
            help="Run embedding generation asynchronously (via Celery)",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force re-generation even if embedding already exists",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be processed without actually generating embeddings",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=100,
            help="Number of papers to process per batch (default: 100)",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Maximum number of papers to process",
        )
        parser.add_argument(
            "--missing-only",
            action="store_true",
            help="Only process papers that don't have embeddings",
        )

    def handle(self, *args, **options):
        paper_ids = options["paper_id"]
        published_start = options.get("published_start")
        published_end = options.get("published_end")
        created_start = options.get("created_start")
        created_end = options.get("created_end")
        dry_run = options.get("dry_run", False)
        force = options.get("force", False)
        batch_size = options.get("batch_size", 100)
        limit = options.get("limit")
        missing_only = options.get("missing_only", False)

        # Build queryset based on filters
        papers_qs = Paper.objects.all()

        # Priority 1: Published date range
        if published_start:
            published_start_dt = parser.parse(published_start)
            if published_end:
                published_end_dt = parser.parse(published_end)
            else:
                published_end_dt = timezone.now()

            self.stdout.write(
                f"Filtering by PUBLISHED date: {published_start_dt} to {published_end_dt}"
            )
            papers_qs = papers_qs.filter(
                paper_publish_date__gte=published_start_dt,
                paper_publish_date__lte=published_end_dt,
            )

        # Priority 2: Created date range
        elif created_start:
            created_start_dt = parser.parse(created_start)
            if created_end:
                created_end_dt = parser.parse(created_end)
            else:
                created_end_dt = timezone.now()

            self.stdout.write(
                f"Filtering by CREATED date: {created_start_dt} to {created_end_dt}"
            )
            papers_qs = papers_qs.filter(
                created_date__gte=created_start_dt,
                created_date__lte=created_end_dt,
            )

        # Priority 3: Specific paper IDs
        elif paper_ids:
            papers_qs = papers_qs.filter(id__in=paper_ids)

        # Filter for missing embeddings if requested
        if missing_only or (not force and not paper_ids):
            papers_qs = papers_qs.filter(title_abstract_embedding__isnull=True)
            self.stdout.write("Filtering for papers without embeddings")

        # Only papers with titles
        papers_qs = papers_qs.exclude(title__isnull=True).exclude(title="")

        # Apply limit
        if limit:
            papers_qs = papers_qs[:limit]
            self.stdout.write(f"Limiting to {limit} papers")

        # Get paper IDs
        paper_ids = list(papers_qs.values_list("id", flat=True))

        if not paper_ids:
            self.stdout.write(
                self.style.WARNING("No papers found matching the criteria")
            )
            return

        self.stdout.write(f"\nFound {len(paper_ids)} papers to process\n")

        # Dry run - just show what would be processed
        if dry_run:
            self.stdout.write(
                self.style.WARNING("DRY RUN - No embeddings will be generated")
            )
            for pid in paper_ids[:20]:
                try:
                    paper = Paper.objects.get(id=pid)
                    has_embedding = paper.title_abstract_embedding is not None
                    title_preview = (paper.paper_title or paper.title or "")[:60]
                    self.stdout.write(
                        f'  {paper.id}: "{title_preview}..." '
                        f"embedding={'yes' if has_embedding else 'no'}"
                    )
                except Paper.DoesNotExist:
                    self.stdout.write(f"  {pid}: NOT FOUND")
            if len(paper_ids) > 20:
                self.stdout.write(f"  ... and {len(paper_ids) - 20} more")
            return

        # Process papers
        if options["async"]:
            # Queue batch tasks
            num_batches = (len(paper_ids) + batch_size - 1) // batch_size
            self.stdout.write(
                f"Queuing {num_batches} batch tasks ({batch_size} papers each)..."
            )

            for i in range(0, len(paper_ids), batch_size):
                batch = paper_ids[i : i + batch_size]
                generate_embeddings_batch.apply_async(
                    args=[batch],
                    kwargs={"skip_existing": not force},
                    priority=6,
                )
                self.stdout.write(f"  Queued batch {i // batch_size + 1}/{num_batches}")

            self.stdout.write(
                self.style.SUCCESS(
                    f"\n✓ Queued {num_batches} batch tasks. "
                    "Check Celery logs for progress."
                )
            )

        else:
            # Process synchronously
            self.stdout.write(f"Processing {len(paper_ids)} papers synchronously...\n")

            from paper.services.bedrock_embedding_service import BedrockEmbeddingService

            service = BedrockEmbeddingService()
            processed = 0
            success = 0
            failed = 0
            skipped = 0

            for paper_id in paper_ids:
                try:
                    paper = Paper.objects.get(id=paper_id)
                    title_preview = (paper.paper_title or paper.title or "")[:40]
                    self.stdout.write(f'  {paper.id}: "{title_preview}..."', ending=" ")

                    # Skip if already has embedding (unless force)
                    if paper.title_abstract_embedding and not force:
                        self.stdout.write(self.style.WARNING("skipped (has embedding)"))
                        skipped += 1
                        continue

                    title = paper.paper_title or paper.title
                    if not title:
                        self.stdout.write(self.style.WARNING("skipped (no title)"))
                        skipped += 1
                        continue

                    embedding = service.generate_paper_embedding(
                        title=title, abstract=paper.abstract
                    )

                    if embedding:
                        paper.title_abstract_embedding = embedding
                        paper.save(update_fields=["title_abstract_embedding"])
                        self.stdout.write(
                            self.style.SUCCESS(f"✓ ({len(embedding)} dims)")
                        )
                        success += 1
                    else:
                        self.stdout.write(self.style.ERROR("✗ failed"))
                        failed += 1

                    processed += 1

                except Paper.DoesNotExist:
                    self.stdout.write(self.style.ERROR("not found"))
                    failed += 1
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"error: {e}"))
                    failed += 1

            self.stdout.write("\n" + ("=" * 60))
            self.stdout.write(f"Processed: {processed}")
            self.stdout.write(f"Success: {success}")
            self.stdout.write(f"Failed: {failed}")
            self.stdout.write(f"Skipped: {skipped}")
            self.stdout.write("=" * 60)
