from django_elasticsearch_dsl import Document, Index
from django_elasticsearch_dsl import fields
from django_elasticsearch_dsl import fields as es_fields
from django_elasticsearch_dsl.registries import registry
from elasticsearch_dsl import analyzer, token_filter, tokenizer

from paper.models import Paper
from search.analyzers import content_analyzer, name_analyzer, title_analyzer
from utils import sentry

from .base import BaseDocument


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
        analyzer=title_analyzer,
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
