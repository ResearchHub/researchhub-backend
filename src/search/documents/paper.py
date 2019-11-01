from django_elasticsearch_dsl import Document, fields as es_fields
from django_elasticsearch_dsl.registries import registry
from elasticsearch_dsl import analyzer

from researchhub.settings import DEVELOPMENT, TESTING
from paper.models import Paper

html_strip = analyzer(
    'html_strip',
    tokenizer='standard',
    filter=['lowercase', 'stop', 'snowball'],
    char_filter=['html_strip']
)

@registry.register_document
class PaperDocument(Document):
    title = es_fields.StringField(
        fields={
            'raw': es_fields.StringField(analyzer='keyword'),
            'suggest': es_fields.CompletionField(),
        },
    )
    authors = es_fields.StringField(
        attr='authors_indexing',
        analyzer=html_strip,
        fields={
            'raw': es_fields.StringField(analyzer='keyword', multi=True),
            'suggest': es_fields.CompletionField(multi=True),
        },
    )
    score = es_fields.IntegerField(attr='score_indexing')
    discussion_count = es_fields.IntegerField(attr='discussion_count_indexing')
    votes = es_fields.NestedField(
        attr='votes_indexing',
        properties={
            'vote_type': es_fields.IntegerField(),
            'updated_date': es_fields.DateField(),
        }
    )
    # TODO: Add field for related summary

    class Index:
        name = 'papers'

    class Django:
        model = Paper
        fields = [
            'id',
            'doi',
            'tagline',
            'uploaded_date',
            'paper_publish_date',
        ]

        # Ignore auto updating of Elasticsearch when a model is saved
        # or deleted:
        ignore_signals = (TESTING is True) or (DEVELOPMENT is True)

        # Don't perform an index refresh after every update (overrides global
        # setting):
        auto_refresh = (TESTING is False) or (DEVELOPMENT is False)
