from django.core.management.base import BaseCommand
from django.db.models.functions import Extract

from researchhub_document.models import ResearchhubUnifiedDocument
from hypothesis.models import Hypothesis
from researchhub_document.models import (
    ResearchhubPost
)


class Command(BaseCommand):

    def add_arguments(self, parser):
       parser.add_argument(
          '--save',
           default=False,
           help='Should save the score'
        )
       parser.add_argument(
          '--id',
           default=False,
           help='Only perform for specific id'
        )

    def handle(self, *args, **options):
        docs = ResearchhubUnifiedDocument.objects.order_by('id')

        print('Recalculating hot score')
        save = False

        if options['save']:
            save = True
        if options['id']:
            docs = docs.filter(id=options['id'])

        count = docs.count()
        for i, doc in enumerate(docs):
            try:
                if doc.document_type.upper() in ['DISCUSSION', 'HYPOTHESIS', 'PAPER']:
                    hot_score_tpl = doc.calculate_hot_score_v2(should_save=save)

                print(f'Doc: {doc.id}, {doc.document_type}, score: {hot_score_tpl[0]} - {i + 1}/{count}')

            except Exception as e:
                print(f'Error updating score for paper: {doc.id}', e)
