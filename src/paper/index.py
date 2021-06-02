from algoliasearch_django import AlgoliaIndex
from algoliasearch_django.decorators import register

from paper.models import Paper

@register(Paper)
class PaperIndex(AlgoliaIndex):
    # fields = ('name', 'date')
    settings = {
        'searchableAttributes': ['title', 'paper_title', 'doi', 'abstract'],
    }
    index_name = 'papers'
