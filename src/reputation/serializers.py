from rest_framework import serializers

import ethereum.lib

from reputation.models import Withdrawal, Contribution
from paper.serializers import BasePaperSerializer
from user.serializers import UserSerializer
from summary.serializers import SummarySerializer, SummaryVoteSerializer
from bullet_point.serializers import BulletPointSerializer, BulletPointVoteSerializer
from discussion.serializers import (
    ThreadSerializer,
    CommentSerializer,
    ReplySerializer,
    VoteSerializer as DisVoteSerializer
)


class WithdrawalSerializer(serializers.ModelSerializer):
    user = UserSerializer(default=serializers.CurrentUserDefault())
    token_address = serializers.CharField(
        default=ethereum.lib.RSC_CONTRACT_ADDRESS
    )

    class Meta:
        model = Withdrawal
        fields = '__all__'
        read_only_fields = [
            'amount',
            'token_address',
            'from_address',
            'transaction_hash',
            'paid_date',
            'paid_status',
            'is_removed',
            'is_removed_date',
        ]


def get_model_serializer(model_arg):
    class GenericSerializer(serializers.ModelSerializer):
        class Meta:
            model = model_arg
            fields = '__all__'

    return GenericSerializer


class ContributionSerializer(serializers.ModelSerializer):
    source = serializers.SerializerMethodField()
    paper = BasePaperSerializer()

    class Meta:
        model = Contribution
        fields = '__all__'

    def get_source(self, contribution):
        serializer = None
        app_label = contribution.content_type.app_label
        model_name = contribution.content_type.name
        object_id = contribution.object_id
        model_class = contribution.content_type.model_class()

        if model_name == 'paper':
            paper = model_class.objects.get(id=object_id)
            serializer = BasePaperSerializer(paper, context=self.context)
        elif model_name == 'thread':
            thread = model_class.objects.get(id=object_id)
            serializer = ThreadSerializer(thread, context=self.context)
        elif model_name == 'comment':
            comment = model_class.objects.get(id=object_id)
            serializer = CommentSerializer(comment, context=self.context)
        elif model_name == 'reply':
            reply = model_class.objects.get(id=object_id)
            serializer = ReplySerializer(reply, context=self.context)
        elif model_name == 'summary':
            summary = model_class.objects.get(id=object_id)
            serializer = SummarySerializer(summary, context=self.context)
        elif model_name == 'bullet_point':
            bulletpoint = model_class.objects.get(id=object_id)
            serializer = BulletPointSerializer(
                bulletpoint,
                context=self.context
            )
        elif model_name == 'vote':
            if app_label == 'discussion':
                serializer = DisVoteSerializer
            elif app_label == 'summary':
                serializer = SummaryVoteSerializer
            elif app_label == 'bullet_point':
                serializer = BulletPointVoteSerializer

        if serializer is not None:
            return serializer.data
        return None
