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
        today = datetime.now()
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
            created_date__lte=today,
            created_date__gte=paper_sync_stop_date
        )
        for paper in papers.iterator():
            try:
                unified_doc_exists = UnifiedDocument.objects.filter(
                    paper=paper
                ).exists()
                if (unified_doc_exists is False):
                    hot_score = paper.calculate_hot_score()
                    score = paper.calculate_score()
                    new_rh_unified_doc = UnifiedDocument.objects.create(
                        document_type=PAPER,
                        hot_score=0 if hot_score is None else hot_score,
                        paper=paper,
                        score=0 if score is None else score
                    )
                    hubs = paper.hubs.all()
                    new_rh_unified_doc.hubs.add(*hubs)
                    new_rh_unified_doc.save()
                return None
            except Exception as exception:
                print(
                  "ERROR (backfill_rh_unified_doc_and_paper): ", exception
                )
