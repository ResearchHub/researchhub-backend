from django_elasticsearch_dsl_drf.serializers import DocumentSerializer

from search.documents import CitationEntryDocument


class CitationEntryDocumentSerializer(DocumentSerializer):
    class Meta:
        document = CitationEntryDocument
        fields = (
            "id",
            "doi",
            "citation_type",
            "created_by",
            "created_date",
            "organization",
            "title",
            "fields",
        )
