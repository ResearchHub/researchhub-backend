from django_elasticsearch_dsl import fields as es_fields
from django_elasticsearch_dsl.registries import registry

from citation.models import CitationEntry
from search.analyzers import content_analyzer, name_analyzer, title_analyzer

from .base import BaseDocument


@registry.register_document
class CitationEntryDocument(BaseDocument):
    auto_refresh = True
    id = es_fields.IntegerField(attr="id")
    # title = es_fields.ObjectField(
    #     properties={"title": es_fields.TextField()}
    # )
    title = es_fields.TextField(
        attr="title_indexing",
        # analyzer=title_analyzer,
    )
    # created_by = es_fields.ObjectField(
    #     attr="created_by_indexing",
    #     properties={
    #         "profile_img": es_fields.TextField(),
    #         "id": es_fields.IntegerField(),
    #     },
    # )
    created_by = es_fields.ObjectField(
        attr="created_by_indexing",
        properties={
            "first_name": es_fields.TextField(),
            "last_name": es_fields.TextField(),
            "full_name": es_fields.TextField(),
            "id": es_fields.IntegerField(),
        },
    )

    class Index:
        name = "citation_entry"

    class Django:
        model = CitationEntry
        queryset_pagination = 250

    # def prepare_title(self, instance):
    #     title = instance.fields.get("title", "")
    #     # print(title)
    #     # return title
    #     print(title)
    #     return title
    #     return {"title": title}

    def should_remove_from_index(self, obj):
        return False
