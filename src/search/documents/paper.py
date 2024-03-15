import itertools
import re

from django_elasticsearch_dsl import Document, Index
from django_elasticsearch_dsl import fields
from django_elasticsearch_dsl import fields as es_fields
from django_elasticsearch_dsl.registries import registry
from elasticsearch_dsl import analyzer, token_filter, tokenizer

from paper.models import Paper
from search.analyzers import content_analyzer, name_analyzer, title_analyzer
from utils import sentry

from .base import BaseDocument

# Define custom token filters
shingle_filter = token_filter(
    "shingle_filter",
    type="shingle",
    min_shingle_size=2,
    max_shingle_size=3,
    output_unigrams=True,
)

edge_ngram_filter = token_filter(
    "edge_ngram_filter",
    type="edge_ngram",
    min_gram=1,
    max_gram=20,
)

# Define custom analyzers
shingle_analyzer = analyzer(
    "shingle_analyzer",
    tokenizer="standard",
    filter=["lowercase", shingle_filter],
)

edge_ngram_analyzer = analyzer(
    "edge_ngram_analyzer",
    tokenizer="standard",
    filter=["lowercase", edge_ngram_filter],
)


autocomplete_analyzer = analyzer(
    "autocomplete_analyzer",
    tokenizer=tokenizer("trigram", "nGram", min_gram=1, max_gram=20),
    filter=["lowercase"],
)
from elasticsearch_dsl import analyzer, tokenizer


@registry.register_document
class PaperDocument(BaseDocument):
    auto_refresh = True

    hubs_flat = es_fields.TextField(attr="hubs_indexing_flat")
    discussion_count = es_fields.IntegerField(attr="discussion_count_indexing")
    score = es_fields.IntegerField(attr="score_indexing")
    hot_score = es_fields.IntegerField(attr="hot_score_indexing")
    paper_title = es_fields.TextField(analyzer=title_analyzer)
    paper_publish_date = es_fields.DateField(
        attr="paper_publish_date", format="yyyy-MM-dd"
    )
    abstract = es_fields.TextField(attr="abstract_indexing", analyzer=content_analyzer)
    doi = es_fields.TextField(attr="doi_indexing", analyzer="keyword")
    raw_authors = es_fields.ObjectField(
        attr="raw_authors_indexing",
        properties={
            "first_name": es_fields.TextField(),
            "last_name": es_fields.TextField(),
            "full_name": es_fields.TextField(),
        },
    )
    hubs = es_fields.ObjectField(
        attr="hubs_indexing",
        properties={
            "id": es_fields.IntegerField(),
            "name": es_fields.KeywordField(),
            "slug": es_fields.TextField(),
        },
    )

    slug = es_fields.TextField()
    title_suggest = es_fields.Completion()
    title = es_fields.TextField(
        analyzer=edge_ngram_analyzer,
        search_analyzer="standard",
    )
    updated_date = es_fields.DateField()
    is_open_access = es_fields.BooleanField()
    oa_status = es_fields.KeywordField()
    pdf_license = es_fields.KeywordField()
    external_source = es_fields.KeywordField()

    class Index:
        name = "paper"

    class Django:
        model = Paper
        queryset_pagination = 250
        fields = ["id"]

    def should_remove_from_index(self, obj):
        if obj.is_removed:
            return True

        return False

    # Used specifically for "autocomplete" style suggest feature
    def prepare_title_suggest(self, instance):
        return {
            "input": instance.title.split() + [instance.title],
            "weight": 1,
        }

    def prepare(self, instance):
        try:
            data = super().prepare(instance)
            data["title_suggest"] = self.prepare_title_suggest(instance)
            return data
        except Exception as error:
            print("Paper Indexing error: ", error, "Instance: ", instance.id)
            sentry.log_error(error)
            return False
