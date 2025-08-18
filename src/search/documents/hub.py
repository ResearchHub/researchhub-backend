import logging
import re

from django_opensearch_dsl import fields as es_fields
from django_opensearch_dsl.registries import registry
from opensearchpy import analyzer, token_filter

from hub.models import Hub
from search.analyzers import content_analyzer

from .base import BaseDocument

logger = logging.getLogger(__name__)

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
    name_suggest = es_fields.CompletionField()
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

    def get_queryset(self, filter_=None, exclude=None, count=None):
        return (
            super()
            .get_queryset(filter_=filter_, exclude=exclude, count=count)
            .exclude(namespace="journal")
        )

    # Used specifically for "autocomplete" style suggest feature
    def prepare_name_suggest(self, instance):
        cleaned_name = re.sub(r"[^\w\s]", "", instance.name)
        words = cleaned_name.split()
        # Prioritize results with less words: "Computer Science" > "Computer Science and Engineering"
        weight = 1000 - len(words)

        return {
            "input": words + [cleaned_name],
            "weight": max(weight, 1),
        }

    def prepare(self, instance):
        try:
            data = super().prepare(instance)
        except Exception as e:
            logger.error(f"Failed to prepare data for hub {instance.id}: {e}")
            return None

        try:
            data["name_suggest"] = self.prepare_name_suggest(instance)
        except Exception as e:
            logger.warning(f"Failed to prepare name suggest for hub {instance.id}: {e}")
            data["name_suggest"] = []

        return data

    def should_index_object(self, obj):
        return not obj.is_removed
