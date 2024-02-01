from django.core.management.base import BaseCommand
from paper.models import Paper
from utils.parsers import rebuild_sentence_from_inverted_index

class Command(BaseCommand):
    help = 'Update paper abstracts from open_alex_raw_json'

    def handle(self, *args, **kwargs):
        papers = Paper.objects.filter(abstract__isnull=True, open_alex_raw_json__isnull=False).iterator()

        to_update = []
        for paper in papers:
            inverted_index = paper.open_alex_raw_json.get('abstract_inverted_index', None)
            if inverted_index:
                paper.abstract = rebuild_sentence_from_inverted_index(inverted_index)
                to_update.append(paper)

            if len(to_update) >= 100:
                Paper.objects.bulk_update(to_update, ['abstract'])
                to_update = []

        if to_update:
            Paper.objects.bulk_update(to_update, ['abstract'])
