from django.core.management.base import BaseCommand
from django.db.models.functions import Extract

from researchhub_document.models import ResearchhubUnifiedDocument
from hypothesis.models import Hypothesis
from researchhub_document.models import (
    ResearchhubPost
)


class Command(BaseCommand):

    def handle(self, *args, **options):
        docs = ResearchhubUnifiedDocument.objects.order_by('id')
        count = docs.count()

        print('Recalculating hot score')
        for i, doc in enumerate(docs):
            try:
                score = 0
                if doc.document_type.upper() in ['DISCUSSION', 'HYPOTHESIS', 'PAPER']:
                    score = doc.calculate_hot_score_v2(debug=False)

                print(f'Doc: {doc.id}, {doc.document_type}, score: {score} - {i + 1}/{count}')

            except Exception as e:
                print(f'Error updating score for paper: {doc.id}', e)
