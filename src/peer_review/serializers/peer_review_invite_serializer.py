from rest_framework.serializers import ModelSerializer, SerializerMethodField, ValidationError
from peer_review.models import PeerReviewInvite
from user.models import User

MINUTES_TO_EXPIRE_INVITE = 10080

class PeerReviewInviteSerializer(ModelSerializer):
    recipient_email = SerializerMethodField()

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

        if data['recipient']:
            recipient_user = User.objects.get(id=data['recipient'])
            data['recipient_email'] = recipient_user.email

        return super(PeerReviewInviteSerializer, self).to_internal_value(data)

    def create(self, validated_data):
        data = validated_data
        instance = PeerReviewInvite.create(**data)
        # instance.send_invitation()

        return instance

    def get_recipient_email(self, obj):
        # If recipient is set, that means user was invited
        # by user id. In this case we should not expose the users's email.
        # This is done to circumvent logic on Invitation class which requires both
        # recipient_email as required field.
        if obj.recipient:
            return None

        return obj.recipient_email
