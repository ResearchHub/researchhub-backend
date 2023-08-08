from django_elasticsearch_dsl_drf.serializers import DocumentSerializer

from search.documents import CitationEntryDocument


class CitationEntryDocumentSerializer(DocumentSerializer):
    class Meta:
        document = CitationEntryDocument
        fields = (
            "id",
            "created_by",
            "organization",
            "title",
        )
