from rest_framework import serializers

import ethereum.lib

from reputation.models import Withdrawal, Contribution
from user.serializers import UserSerializer
from summary.serializers import SummarySerializer, SummaryVoteSerializer
from bullet_point.serializers import (
    BulletPointSerializer,
    BulletPointVoteSerializer
)
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
    paper = serializers.SerializerMethodField()
    content_type = serializers.SerializerMethodField()
    user = UserSerializer()

    class Meta:
        model = Contribution
        fields = '__all__'

    def get_paper(self, contribution):
        from paper.serializers import ContributionPaperSerializer
        serializer = ContributionPaperSerializer(contribution.paper)
        return serializer.data

    def get_content_type(self, contribution):
        app_label = contribution.content_type.app_label
        model_name = contribution.content_type.name
        return {'app_label': app_label, 'model_name': model_name}

    def get_source(self, contribution):
        from paper.serializers import ContributionPaperSerializer
        from purchase.serializers import PurchaseSerializer

        serializer = None
        context = self.context
        app_label = contribution.content_type.app_label
        model_name = contribution.content_type.name
        object_id = contribution.object_id
        model_class = contribution.content_type.model_class()
        obj = model_class.objects.get(id=object_id)

        if model_name == 'paper':
            serializer = ContributionPaperSerializer(obj, context=context)
        elif model_name == 'thread':
            serializer = ThreadSerializer(obj, context=context)
        elif model_name == 'comment':
            serializer = CommentSerializer(obj, context=context)
        elif model_name == 'reply':
            serializer = ReplySerializer(obj, context=context)
        elif model_name == 'summary':
            serializer = SummarySerializer(obj, context=context)
        elif model_name == 'bullet_point':
            serializer = BulletPointSerializer(obj, context=context)
        elif model_name == 'purchase':
            context['exclude_source'] = True
            context['exclude_stats'] = True
            serializer = PurchaseSerializer(obj, context=context)
        elif model_name == 'vote':
            if app_label == 'discussion':
                serializer = DisVoteSerializer(obj, context=context)
            elif app_label == 'summary':
                serializer = SummaryVoteSerializer(obj, context=context)
            elif app_label == 'bullet_point':
                serializer = BulletPointVoteSerializer(obj, context=context)

        if serializer is not None:
            return serializer.data
        return None
