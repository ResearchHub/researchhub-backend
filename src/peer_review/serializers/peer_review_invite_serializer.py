from rest_framework.serializers import ModelSerializer, SerializerMethodField, ValidationError
from peer_review.models import (
    PeerReviewInvite,
    PeerReview
)
from user.models import User
from researchhub.serializers import DynamicModelFieldSerializer

MINUTES_TO_EXPIRE_INVITE = 10080

class DynamicPeerReviewInviteSerializer(
    DynamicModelFieldSerializer,
):
    recipient = SerializerMethodField()

    class Meta:
        model = PeerReviewInvite
        fields = '__all__'

    def get_recipient(self, obj):
        from user.serializers import DynamicUserSerializer

        context = self.context
        _context_fields = context.get("pr_dpris_get_recipient", {})

        serializer = DynamicUserSerializer(
            obj.recipient,
            context=context,
            **_context_fields
        )
        return serializer.data        

class PeerReviewInviteSerializer(ModelSerializer):
    peer_review = SerializerMethodField()

    class Meta:
        model = PeerReviewInvite
        fields = [
            'inviter',
            'recipient',
            'recipient_email',
            'peer_review_request',
            'peer_review',
            'id',
            'status',
            'created_date',
        ]
        read_only_fields = [
            'id',
            'status',
            'created_date',
        ]

    def to_internal_value(self, data):
        data['expiration_time'] = MINUTES_TO_EXPIRE_INVITE

        if 'recipient' in data:
            recipient_user = User.objects.get(id=data['recipient'])
            data['recipient_email'] = recipient_user.email

        return super(PeerReviewInviteSerializer, self).to_internal_value(data)

    def create(self, validated_data):
        data = validated_data
        instance = PeerReviewInvite.create(**data)
        # instance.send_invitation()
        return instance

    def get_peer_review(self, obj):
        from peer_review.serializers import PeerReviewSerializer

        review = obj.peer_review_request.peer_review
        if review:
            serializer = PeerReviewSerializer(review)
            return serializer.data

        return None
