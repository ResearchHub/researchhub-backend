from rest_framework.serializers import ModelSerializer, SerializerMethodField, ValidationError
from peer_review.models import PeerReviewInvite

class PeerReviewInviteSerializer(ModelSerializer):
    class Meta:
        model = PeerReviewInvite
        fields = [
            'invited_user',
            'invited_email',
            'invited_by_user',
            'peer_review_request',
            'id',
            'status',
            'created_date',
        ]
        read_only_fields = [
            'id',
            'status',
            'created_date',
        ]

    def validate(self, data):
        return data

    def create(self, validated_data):
        data = validated_data
        data['invited_by_user'] = self.context['request'].user

        instance = PeerReviewInvite(**data)
        instance.save()
        return instance
