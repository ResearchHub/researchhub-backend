'''
Add or create figures for all papers without figures.
'''
from django.core.management.base import BaseCommand

from paper.models import Paper, Figure


class Command(BaseCommand):

    def handle(self, *args, **options):
        exclude_ids = Figure.objects.all().distinct('paper').values_list(
            'paper',
            flat=True
        )
        papers = Paper.objects.filter(file__isnull=False, uploaded_date__gte="2020-12-20").order_by('-id').exclude(id__in=exclude_ids)
        count = papers.count()
        for i, paper in enumerate(papers):
            print('{} / {}'.format(i, count))
            try:
                paper.extract_pdf_preview(use_celery=False)
            except Exception as e:
                self.stdout.write(self.style.ERROR(
                    f'Failed to queue task for paper {paper.id}: {e}'
                ))

        self.stdout.write(self.style.SUCCESS(f'Done adding figures papers'))
