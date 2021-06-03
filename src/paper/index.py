from algoliasearch_django import AlgoliaIndex
from algoliasearch_django.decorators import register

from paper.models import Paper


@register(Paper)
class PaperIndex(AlgoliaIndex):
    index_name = 'papers'
    fields = (
        'paper_title',
        'title',
        'publication_type',
        'external_source',
        'uploaded_date',
        'abstract',
        'is_removed',
        'doi',
        'hot_score',
        'paper_authors'
    )
    settings = {
        'searchableAttributes': [
            'title',
            'paper_title',
            'doi',
            'abstract',
            'paper_authors',
        ],
    }
