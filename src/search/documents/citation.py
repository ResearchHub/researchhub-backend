from django_elasticsearch_dsl import fields as es_fields
from django_elasticsearch_dsl.registries import registry

from citation.models import CitationEntry

from .base import BaseDocument


@registry.register_document
class CitationEntryDocument(BaseDocument):
    id = es_fields.IntegerField(attr="id")
    fields = es_fields.NestedField(attr="fields")
    doi = es_fields.TextField(attr="doi")
    citation_type = es_fields.TextField(attr="citation_type")
    created_by = es_fields.ObjectField(
        attr="created_by_indexing",
        properties={
            "id": es_fields.IntegerField(),
            "first_name": es_fields.TextField(),
            "last_name": es_fields.TextField(),
            "full_name": es_fields.TextField(),
        },
    )
    created_date = es_fields.DateField(attr="created_date")
    organization = es_fields.ObjectField(
        attr="organization_indexing",
        properties={
            "id": es_fields.IntegerField(),
            "name": es_fields.TextField(),
        },
    )

    class Index:
        name = "citation_entry"

    class Django:
        model = CitationEntry
        queryset_pagination = 250
