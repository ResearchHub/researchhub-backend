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
    summary = es_fields.TextField(attr="summary_indexing")
    # title = es_fields.TextField(analyzer=edge_ngram_analyzer)
    paper_title = es_fields.TextField(analyzer=title_analyzer)
    paper_publish_date = es_fields.DateField(
        attr="paper_publish_date", format="yyyy-MM-dd"
    )
    abstract = es_fields.TextField(attr="abstract_indexing", analyzer=content_analyzer)
    doi = es_fields.TextField(attr="doi_indexing", analyzer="keyword")
    authors = es_fields.TextField(attr="authors_indexing", analyzer=name_analyzer)
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
            "hub_image": es_fields.TextField(),
            "id": es_fields.IntegerField(),
            "is_locked": es_fields.TextField(),
            "is_removed": es_fields.TextField(),
            "name": es_fields.KeywordField(),
        },
    )
    # title_suggest = es_fields.CompletionField()
    # title = fields.TextField(required=True, analyzer=autocomplete_analyzer) # This is it....

    title_suggest = es_fields.Completion()
    title = es_fields.TextField(
        analyzer=edge_ngram_analyzer,
        search_analyzer="standard",
    )

    class Index:
        name = "paper"
        # settings = {
        #     'number_of_shards': 1,
        #     'number_of_replicas': 0,
        #     'max_ngram_diff': 20 # This seems to be important due to the constraint for max_ngram_diff beeing 1
        # }

    class Django:
        model = Paper
        queryset_pagination = 250
        fields = ["id"]

    def should_remove_from_index(self, obj):
        if obj.is_removed:
            return True

        return False

    # Used specifically for "autocomplete" style suggest feature
    # def prepare_title_suggest(self, instance):
    #     return {
    #         "input": [instance.title],
    #         "weight": 1,  # Adjust weight as needed
    #     }

    # def prepare(self, instance):
    #     try:
    #         print("instance", instance)
    #         data = super().prepare(instance)
    #         data["title_suggest"] = self.prepare_title_suggest(instance)
    #         return data
    #     except Exception as error:
    #         print("Paper Indexing error: ", error)
    #         sentry.log_error(error)
    #         return False

    # Used specifically for "autocomplete" style suggest feature
    def prepare_title_suggest(self, instance):
        return {
            "input": instance.title.split() + [instance.title],
            "weight": 1,
        }

    def prepare(self, instance):
        try:
            print("instance", instance)
            data = super().prepare(instance)
            data["title_suggest"] = self.prepare_title_suggest(instance)
            return data
        except Exception as error:
            print("Paper Indexing error: ", error)
            sentry.log_error(error)
            return False
