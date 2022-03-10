'''
Add tags for all papers using the abstract
'''
from django.core.management.base import BaseCommand

from paper.models import Paper
from tag.models import Tag

import nltk
from nltk.corpus import stopwords
import yake


class Command(BaseCommand):

    def handle(self, *args, **options):
        papers = Paper.objects.filter(abstract__isnull=False)
        print('Adding tags to papers')
        nltk.download('stopwords')
        nltk.download('punkt')
        for paper in papers:
            keyword_settings = {
                "lan": "en",
                "n": 1,
                "dedupLim": 0.1,
                "top": 3,
                "features": None
            }

            custom_kw_extractor = yake.KeywordExtractor(**keyword_settings)

            abstract = paper.abstract.lower() + paper.title.lower()

            # Get a set of common stopwords (i.e. "in", "the", etc...)
            stop_words = set(stopwords.words('english'))

            keywords = custom_kw_extractor.extract_keywords(abstract)

            formatted_keys = [key[0] for key in keywords]

            tags = []

            for key in formatted_keys:
                t, _ = Tag.objects.get_or_create(key=key)
                tags.append(t.id)

            paper.tags.set(tags)


