from django_elasticsearch_dsl_drf.serializers import DocumentSerializer

from citation.models import CitationEntry
from citation.serializers import CitationEntrySerializer
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

    def to_representation(self, document):
        citation_id = document["id"]
        citation = CitationEntry.objects.get(id=citation_id)
        data = CitationEntrySerializer(citation).data
        return data
