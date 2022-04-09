from rest_framework.serializers import ModelSerializer, SerializerMethodField, ValidationError
from peer_review.models import (
    PeerReviewRequest,
    PeerReviewInvite,
)

class PeerReviewRequestSerializer(ModelSerializer):
    invites = SerializerMethodField()
    peer_review = SerializerMethodField()

    class Meta:
        model = PeerReviewRequest
        fields = [
            'requested_by_user',
            'peer_review',
            'unified_document',
            'doc_version',
            'id',
            'status',
            'created_date',
            'invites',
        ]
        read_only_fields = [
            'status',
            'id',
            'created_date',
        ]

    def validate(self, data):
        return data

    def create(self, validated_data):
        data = validated_data
        data['requested_by_user'] = self.context['request'].user

        instance = PeerReviewRequest(**data)
        instance.save()
        return instance

    def get_invites(self, obj):
        from peer_review.serializers import PeerReviewInviteSerializer

        invites = PeerReviewInvite.objects.filter(peer_review_request=obj.id)
        serializer = PeerReviewInviteSerializer(
            invites,
            many=True,
        )

        return serializer.data

    def get_peer_review(self, obj):
        print('something')