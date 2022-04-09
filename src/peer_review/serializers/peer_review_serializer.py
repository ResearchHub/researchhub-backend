from rest_framework.serializers import ModelSerializer, SerializerMethodField, ValidationError
from peer_review.models import (
    PeerReview,
)


class PeerReviewSerializer(ModelSerializer):
    class Meta:
        model = PeerReview
        fields = [
            'id',
            'assigned_user',
            'unified_document',
        ]
