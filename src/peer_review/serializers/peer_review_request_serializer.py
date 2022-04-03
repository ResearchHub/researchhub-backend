from rest_framework.serializers import ModelSerializer, SerializerMethodField
from peer_review.models import PeerReviewRequest

class PeerReviewRequestSerializer(ModelSerializer):
    class Meta:
        model = PeerReviewRequest
        fields = [
            'status',
        ]
        read_only_fields = [
            'id',
            'status',
            'invited_by_user_id',
            'invited_user_id',
        ]

    def validate_content(self,value):
        print('validating data')        
        return value

    def create(self, validated_data):
        print('********')
        print(validated_data)
        print('********')
