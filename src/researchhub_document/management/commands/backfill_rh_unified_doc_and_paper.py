import datetime

from django.core.management.base import BaseCommand

from paper.models import Paper
from researchhub_document.models import (
  ResearchhubUnifiedDocument as UnifiedDocument
)
from researchhub_document.related_models.constants.document_type import (
  PAPER
)


class Command(BaseCommand):

    def handle(self, *args, **options):
        today = datetime.datetime.now()
        # change stop date after confirming that it's working properly
        paper_sync_stop_date = datetime.datetime(
            year=2021,
            month=1,
            day=1,
            hour=0,
            minute=0,
            second=0
        )
        papers = Paper.objects.filter(
            uploaded_date__lte=today,
            uploaded_date__gte=paper_sync_stop_date
        )
        count = papers.count()
        for i, paper in enumerate(papers.iterator()):
            print(f'{i + 1}/{count}')
            try:
                unified_doc = UnifiedDocument.objects.filter(
                    paper=paper
                )
                if not unified_doc.exists():
                    hot_score = paper.hot_score
                    score = paper.calculate_score()
                    is_removed = paper.is_removed
                    published_date = paper.published_date
                    kwargs = {
                        'document_type': PAPER,
                        'hot_score': 0 if hot_score is None else hot_score,
                        'paper': paper,
                        'score': 0 if score is None else score,
                        'is_removed': is_removed,
                        'published_date': published_date
                    }

                    new_rh_unified_doc = UnifiedDocument.objects.create(
                        **kwargs
                    )
                    hubs = paper.hubs.all()
                    new_rh_unified_doc.hubs.add(*hubs)
                    new_rh_unified_doc.save()
            except Exception as exception:
                print(
                  'ERROR (backfill_rh_unified_doc_and_paper): ', exception
                )
