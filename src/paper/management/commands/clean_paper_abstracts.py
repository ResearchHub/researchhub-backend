'''
Clean HTML tags in abstract
'''

import utils.sentry as sentry

from bs4 import BeautifulSoup

from django.core.management.base import BaseCommand

from paper.models import Paper


class Command(BaseCommand):

    def handle(self, *args, **options):
        papers = Paper.objects.iterator()
        paper_count = Paper.objects.count()

        for i, paper in enumerate(papers):
            print(f'{i}/{paper_count}')
            try:
                abstract = paper.abstract
                if abstract:
                    soup = BeautifulSoup(abstract, 'html.parser')
                    strings = soup.strings
                    cleaned_text = ' '.join(strings)
                    cleaned_text = cleaned_text.replace('\n', '')
                    cleaned_text = cleaned_text.replace('\r', '')
                    paper.abstract = cleaned_text
                    paper.save()
            except Exception as e:
                print(e)
                sentry.log_error(e)
