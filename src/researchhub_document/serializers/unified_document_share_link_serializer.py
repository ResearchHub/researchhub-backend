from rest_framework.serializers import ModelSerializer

from researchhub_document.related_models.unified_document_share_link_model import (
    UnifiedDocumentShareLink,
)


class UnifiedDocumentShareLinkSerializer(ModelSerializer):
    """The link itself, returned to the user who generated it.

    Only the token is exposed; assembling the shareable URL is the frontend's
    concern.
    """

    class Meta:
        model = UnifiedDocumentShareLink
        fields = ["token", "expires_at", "created_date"]
