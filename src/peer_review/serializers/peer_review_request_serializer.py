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
        uni_doc = data['unified_document']
        requested_by_user = self.context['request'].user

        is_author_requesting_review = uni_doc.authors.filter(
            id=requested_by_user.id
        ).exists()

        if is_author_requesting_review is False:
            raise ValidationError(
                'Peer reviews must be requested by authors or moderators'
            )

        return data

    def create(self, validated_data):
        data = validated_data
        data['requested_by_user'] = self.context['request'].user

        instance = PeerReviewRequest(**data)
        instance.save()
        return instance
