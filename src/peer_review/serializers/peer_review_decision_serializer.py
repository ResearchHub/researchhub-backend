from rest_framework.serializers import ModelSerializer, SerializerMethodField, ValidationError
from peer_review.models import (
    PeerReviewDecision,
)
from user.models import User
from discussion.models import Thread
from researchhub.settings import TESTING
from reputation.models import Contribution
from reputation.tasks import create_contribution


MINUTES_TO_EXPIRE_INVITE = 10080

class PeerReviewDecisionSerializer(ModelSerializer):
    peer_review = SerializerMethodField()
    discussion_thread = SerializerMethodField()

    class Meta:
        model = PeerReviewDecision
        fields = [
            'id',
            'peer_review',
            'unified_document',
            'doc_version',
            'decision',
            'discussion_thread',
            'created_date',
        ]
        read_only_fields = [
            'id',
            'created_date',
        ]

    def validate(self, data):
        return data

    def _create_contribution(self, decision):
        use_async = True
        if TESTING:
            use_async = False

        app_label = decision._meta.app_label
        model = decision._meta.model.__name__.lower()
        user_id = decision.peer_review.assigned_user.id
        unified_doc_id = decision.unified_document.id
        obj_id = decision.id

        if use_async:
            create_contribution.apply_async(
                (
                    Contribution.PEER_REVIEWER,
                    {'app_label': app_label, 'model': model},
                    user_id,
                    unified_doc_id,
                    obj_id
                ),
                priority=1,
                countdown=10
            )
        else:
            create_contribution(
                contribution_type=Contribution.PEER_REVIEWER,
                instance_type={'app_label': app_label, 'model': model},
                user_id=user_id,
                unified_doc_id=unified_doc_id,
                object_id=obj_id
            )


    def create(self, validated_data):
        data = validated_data

        thread = None
        if 'discussion' in self.context['request'].data:
            thread = Thread.objects.create(
                **(self.context['request'].data['discussion']),
                peer_review=self.context['peer_review'],
                created_by=self.context['request'].user,
            )

        instance = PeerReviewDecision.objects.create(
            **data,
            peer_review=self.context['peer_review'],
            discussion_thread=thread,
        )

        self._create_contribution(instance)

        return instance

    def get_peer_review(self, obj):
        from peer_review.serializers import PeerReviewSerializer

        review = obj.peer_review
        if review:
            serializer = PeerReviewSerializer(review)
            return serializer.data

        return None

    def get_discussion_thread(self, obj):
        from discussion.serializers import ThreadSerializer

        discussion_thread = obj.discussion_thread
        if discussion_thread:
            serializer = ThreadSerializer(discussion_thread)
            return serializer.data

        return None
