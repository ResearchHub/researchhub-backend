"""
Management command for enriching papers with Altmetric metrics.
"""

from django.core.management.base import BaseCommand

from paper.ingestion.clients.enrichment.altmetric import AltmetricClient
from paper.ingestion.mappers.enrichment.altmetric import AltmetricMapper
from paper.ingestion.services import PaperMetricsEnrichmentService
from paper.models import Paper


class Command(BaseCommand):
    help = "Enrich papers with Altmetric metrics data"

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=7,
            help="Number of days to look back for papers (default: 7)",
        )
        parser.add_argument(
            "--paper-id",
            type=int,
            help="Enrich a specific paper by ID (overrides --days)",
        )

    def handle(self, *args, **options):
        days = options["days"]
        paper_id = options.get("paper_id")

        service = PaperMetricsEnrichmentService(AltmetricClient(), AltmetricMapper())

        if paper_id:
            # Enrich single paper
            self.stdout.write(f"Enriching paper {paper_id}...")

            try:
                paper = Paper.objects.get(id=paper_id)
                result = service.enrich_paper_with_altmetric(paper)

                if result.status == "success":
                    self.stdout.write(
                        f"Successfully enriched paper {paper_id} "
                        f"(score: {result.altmetric_score or 'N/A'})"
                    )
                elif result.status == "skipped":
                    self.stdout.write(f"Skipped paper {paper_id}: {result.reason}")
                elif result.status == "not_found":
                    self.stdout.write(f"No Altmetric data found for paper {paper_id}")
                else:
                    self.stdout.write(
                        f"Error enriching paper {paper_id}: {result.reason or 'unknown'}"
                    )

            except Paper.DoesNotExist:
                self.stdout.write(f"Paper {paper_id} not found")

        else:
            # Enrich papers from last N days
            self.stdout.write(f"Enriching papers from last {days} days...")

            # Get papers
            papers = service.get_recent_papers_with_dois(days)

            if not papers:
                self.stdout.write(f"No papers with DOIs found in last {days} days")
                return

            self.stdout.write(f"Enriching {len(papers)} papers...")

            # Enrich papers
            results = service.enrich_papers_batch(papers)

            # Display results
            self.stdout.write(f"Total papers: {results.total}")
            self.stdout.write(f"Successful: {results.success_count}")
            self.stdout.write(f"Not found: {results.not_found_count}")
            self.stdout.write(f"Errors: {results.error_count}")
            self.stdout.write(f"Errors: {results.error_count}")
