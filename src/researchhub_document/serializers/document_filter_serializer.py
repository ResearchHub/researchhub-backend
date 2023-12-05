from researchhub.serializers import DynamicModelFieldSerializer
from researchhub_document.models import DocumentFilter


class DynamicDocumentFilterSerializer(DynamicModelFieldSerializer):
    class Meta:
        model = DocumentFilter
        fields = "__all__"
