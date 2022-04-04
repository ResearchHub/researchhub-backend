from rest_framework.serializers import ModelSerializer, SerializerMethodField, ValidationError
from peer_review.models import PeerReviewRequest

class PeerReviewRequestSerializer(ModelSerializer):
    class Meta:
        model = PeerReviewRequest
        fields = [
            'requested_by_user',
            'unified_document',
            'doc_version',
            'id',
            'status',
        ]
        read_only_fields = [
            'status',
            'id',
        ]

    def validate(self, data):
        return data

    def create(self, validated_data):
        data = validated_data
        data['requested_by_user'] = self.context['request'].user

        instance = PeerReviewRequest(**data)
        instance.save()
        return instance
