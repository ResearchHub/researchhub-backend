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
        papers = Paper.objects.exclude(id__in=exclude_ids)
        for paper in papers:
            try:
                paper.extract_figures()
                paper.extract_pdf_preview()
                self.stdout.write(self.style.SUCCESS(
                    f'Queued task to add figures for paper {paper.id}'
                ))
            except Exception as e:
                self.stdout.write(self.style.ERROR(
                    f'Failed to queue task for paper {paper.id}: {e}'
                ))

        self.stdout.write(self.style.SUCCESS(f'Done adding figures papers'))
