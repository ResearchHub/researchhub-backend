from django.core.management.base import BaseCommand
from django.db import transaction

from paper.models import Citation, Paper
from paper.related_models.citation_model import Source


class Command(BaseCommand):
    help = "Backfills the citation table with citation counts for each paper"

    def handle(self, *args, **options):
        max_paper_id = Paper.objects.all().order_by("-id").first().id
        batch_size = 10000
        with transaction.atomic():
            start_id = 0
            end_id = start_id + batch_size

            while start_id < max_paper_id:
                papers = Paper.objects.filter(id__gte=start_id, id__lt=end_id)

                for paper in papers.iterator():
                    citation_count = paper.citations
                    source = Source.Legacy.value
                    if paper.openalex_id:
                        source = Source.OpenAlex.value

                    citation = Citation(
                        paper=paper,
                        total_citation_count=citation_count,
                        citation_change=citation_count,
                        source=source,
                    )

                    citation.save()

                start_id += end_id
                end_id = start_id + batch_size

            self.stdout.write(
                self.style.SUCCESS("Successfully backfilled citation table")
            )
