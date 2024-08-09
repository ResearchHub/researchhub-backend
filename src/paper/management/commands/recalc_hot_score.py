from dateutil import parser
from django.core.management.base import BaseCommand

from researchhub_document.models import ResearchhubUnifiedDocument


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

      parser.add_argument(
        '--start_date',
        help='Perform for date starting'
      )

    def handle(self, *args, **options):
        docs = ResearchhubUnifiedDocument.objects.filter(is_removed=False).order_by('id')

        print('Recalculating hot score')
        save = False

        if options['save']:
            save = True
        if options['id']:
            docs = docs.filter(id=options['id'])
        if options['start_date']:
            print(f"Calculating for docs GTE: {options['start_date']}")
            start_date = parser.parse(options['start_date'])
            docs = docs.filter(created_date__gte=start_date)

        count = docs.count()
        for i, doc in enumerate(docs):
            try:
                if doc.document_type.upper() in ['DISCUSSION', 'PAPER']:
                    hot_score_tpl = doc.calculate_hot_score_v2(should_save=save)

                    print(f'Doc: {doc.id}, {doc.document_type}, score: {hot_score_tpl[0]} - {i + 1}/{count}')

            except Exception as e:
                print(f'Error updating score for paper: {doc.id}', e)
