from django_elasticsearch_dsl import fields as es_fields
from django_elasticsearch_dsl.registries import registry

from paper.models import Paper
from search.analyzers import content_analyzer, name_analyzer, title_analyzer

from .base import BaseDocument


@registry.register_document
class PaperDocument(BaseDocument):
    auto_refresh = True

    hubs_flat = es_fields.TextField(attr="hubs_indexing_flat")
    discussion_count = es_fields.IntegerField(attr="discussion_count_indexing")
    score = es_fields.IntegerField(attr="score_indexing")
    hot_score = es_fields.IntegerField(attr="hot_score_indexing")
    summary = es_fields.TextField(attr="summary_indexing")
    title = es_fields.TextField(analyzer=title_analyzer)
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
