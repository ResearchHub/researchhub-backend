from rest_framework.serializers import ModelSerializer, SerializerMethodField, ValidationError
from peer_review.models import PeerReviewInvite
from user.models import User

MINUTES_TO_EXPIRE_INVITE = 10080

class PeerReviewInviteSerializer(ModelSerializer):

    class Meta:
        model = PeerReviewInvite
        fields = [
            'inviter',
            'recipient',
            'recipient_email',
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

