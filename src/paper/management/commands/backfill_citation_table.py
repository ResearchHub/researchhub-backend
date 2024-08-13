from django.core.management.base import BaseCommand
from django.core.paginator import Paginator
from django.db import transaction

from paper.models import Citation, Paper
from paper.related_models.citation_model import Source


class Command(BaseCommand):
    help = "Backfills the citation table with citation counts for each paper"

    def handle(self, *args, **options):
        batch_size = 1000
        with transaction.atomic():
            queryset = Paper.objects.all()
            paginator = Paginator(queryset, batch_size)

            citations_to_create = []

            for page_number in paginator.page_range:
                page = paginator.page(page_number)

                for paper in page.object_list:
                    if Citation.objects.filter(paper=paper).exists():
                        continue

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

                    citations_to_create.append(citation)

                Citation.objects.bulk_create(citations_to_create)

                citations_to_create = []

            self.stdout.write(
                self.style.SUCCESS("Successfully backfilled citation table")
            )
