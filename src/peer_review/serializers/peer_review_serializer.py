from rest_framework.serializers import ModelSerializer, SerializerMethodField, ValidationError
from peer_review.models import (
    PeerReview,
)
from researchhub.serializers import DynamicModelFieldSerializer


class PeerReviewSerializer(ModelSerializer):
    class Meta:
        model = PeerReview
        fields = [
            'id',
            'assigned_user',
            'unified_document',
        ]

class DynamicPeerReviewSerializer(
    DynamicModelFieldSerializer,
):
    class Meta:
        model = PeerReview
        fields = '__all__'