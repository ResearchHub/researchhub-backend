from django_elasticsearch_dsl import fields as es_fields
from django_elasticsearch_dsl.registries import registry
from elasticsearch_dsl import analyzer, token_filter, tokenizer

from hub.models import Hub
from search.analyzers import content_analyzer, title_analyzer

from .base import BaseDocument

edge_ngram_filter = token_filter(
    "edge_ngram_filter",
    type="edge_ngram",
    min_gram=1,
    max_gram=20,
)

edge_ngram_analyzer = analyzer(
    "edge_ngram_analyzer",
    tokenizer="standard",
    filter=["lowercase", edge_ngram_filter],
)


@registry.register_document
class HubDocument(BaseDocument):
    auto_refresh = True
    queryset_pagination = 250
    description = es_fields.TextField(attr="description", analyzer=content_analyzer)
    name_suggest = es_fields.Completion()
    name = es_fields.TextField(
        analyzer=edge_ngram_analyzer,
        search_analyzer="standard",
    )

    class Index:
        name = "hub"

    class Django:
        model = Hub
        fields = [
            "id",
            "slug",
            "paper_count",
            "discussion_count",
        ]

    # Used specifically for "autocomplete" style suggest feature
    def prepare_name_suggest(self, instance):
        return {
            "input": instance.name.split() + [instance.name],
            "weight": 1,
        }

    def prepare(self, instance):
        data = super().prepare(instance)
        data["name_suggest"] = self.prepare_name_suggest(instance)

        return data

    def should_remove_from_index(self, obj):
        if obj.is_removed:
            return True

        return False
