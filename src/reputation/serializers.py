from rest_framework import serializers

import ethereum.lib
from bullet_point.serializers import BulletPointSerializer, BulletPointVoteSerializer
from discussion.models import Comment, Reply, Thread
from discussion.reaction_models import Vote as DisVote
from discussion.serializers import (
    CommentSerializer,
    DynamicCommentSerializer,
    DynamicReplySerializer,
    DynamicThreadSerializer,
    DynamicVoteSerializer,
    ReplySerializer,
    ThreadSerializer,
)
from discussion.serializers import VoteSerializer as DisVoteSerializer
from paper.models import Paper
from purchase.models import Purchase
from reputation.models import Contribution, Deposit, Distribution, Withdrawal
from researchhub.serializers import DynamicModelFieldSerializer
from summary.serializers import SummarySerializer, SummaryVoteSerializer
from user.models import Author
from user.serializers import (
    DynamicAuthorSerializer,
    DynamicUserSerializer,
    UserSerializer,
)
from utils import sentry


class ProofRelatedField(serializers.RelatedField):
    """
    A custom field to use for the `source` generic relationship.
    """

    def to_representation(self, value):
        """
        Serialize tagged objects to a simple textual representation.
        """
        from discussion.serializers import DynamicVoteSerializer
        from paper.serializers import DynamicPaperSerializer
        from purchase.serializers import PurchaseSerializer

        if isinstance(value, Comment):
            return CommentSerializer(value).data
        elif isinstance(value, Thread):
            return ThreadSerializer(value).data
        elif isinstance(value, Reply):
            return ReplySerializer(value).data
        elif isinstance(value, DisVote):
            return DisVoteSerializer(value).data
        elif isinstance(value, Paper):
            paper_include_fields = ["id", "paper_title", "slug", "score"]
            return DynamicPaperSerializer(
                value, _include_fields=paper_include_fields
            ).data
        elif isinstance(value, Purchase):
            return PurchaseSerializer(value, context={"exclude_stats": True}).data

        sentry.log_info(
            "No representation for {} / id: {}".format(str(value), value.id)
        )
        return None


class DistributionSerializer(serializers.ModelSerializer):
    proof_item = ProofRelatedField(read_only=True)

    class Meta:
        model = Distribution
        fields = "__all__"


class DepositSerializer(serializers.ModelSerializer):
    class Meta:
        model = Deposit
        fields = "__all__"


class WithdrawalSerializer(serializers.ModelSerializer):
    user = UserSerializer(default=serializers.CurrentUserDefault())
    token_address = serializers.CharField(default=ethereum.lib.RSC_CONTRACT_ADDRESS)

    class Meta:
        model = Withdrawal
        fields = "__all__"
        read_only_fields = [
            "amount",
            "token_address",
            "from_address",
            "transaction_hash",
            "paid_date",
            "paid_status",
            "is_removed",
            "is_removed_date",
        ]


def get_model_serializer(model_arg):
    class GenericSerializer(serializers.ModelSerializer):
        class Meta:
            model = model_arg
            fields = "__all__"

    return GenericSerializer


class ContributionSerializer(serializers.ModelSerializer):
    source = serializers.SerializerMethodField()
    unified_document = serializers.SerializerMethodField()
    content_type = serializers.SerializerMethodField()
    user = UserSerializer()

    class Meta:
        model = Contribution
        fields = "__all__"

    def get_unified_document(self, contribution):
        from researchhub_document.serializers import (
            ResearchhubUnifiedDocumentSerializer,
        )

        serializer = ResearchhubUnifiedDocumentSerializer(contribution.unified_document)
        return serializer.data

    def get_content_type(self, contribution):
        app_label = contribution.content_type.app_label
        model_name = contribution.content_type.name
        return {"app_label": app_label, "model_name": model_name}

    def get_source(self, contribution):
        from hypothesis.serializers import HypothesisSerializer
        from paper.serializers import ContributionPaperSerializer
        from purchase.serializers import PurchaseSerializer
        from researchhub_document.serializers.researchhub_post_serializer import (
            ResearchhubPostSerializer,
        )

        serializer = None
        context = self.context
        app_label = contribution.content_type.app_label
        model_name = contribution.content_type.name
        object_id = contribution.object_id
        model_class = contribution.content_type.model_class()
        obj = model_class.objects.get(id=object_id)

        if model_name == "paper":
            serializer = ContributionPaperSerializer(obj, context=context)
        elif model_name == "thread":
            serializer = ThreadSerializer(obj, context=context)
        elif model_name == "comment":
            serializer = CommentSerializer(obj, context=context)
        elif model_name == "reply":
            serializer = ReplySerializer(obj, context=context)
        elif model_name == "summary":
            serializer = SummarySerializer(obj, context=context)
        elif model_name == "bullet_point":
            serializer = BulletPointSerializer(obj, context=context)
        elif model_name == "purchase":
            context["exclude_source"] = True
            context["exclude_stats"] = True
            serializer = PurchaseSerializer(obj, context=context)
        elif model_name == "vote":
            if app_label == "discussion":
                serializer = DisVoteSerializer(obj, context=context)
            elif app_label == "summary":
                serializer = SummaryVoteSerializer(obj, context=context)
            elif app_label == "bullet_point":
                serializer = BulletPointVoteSerializer(obj, context=context)
        elif model_name == "researchhub post":
            serializer = ResearchhubPostSerializer(obj, context=context)
        elif model_name == "hypothesis":
            serializer = HypothesisSerializer(obj, context=context)

        if serializer is not None:
            return serializer.data
        return None


class DynamicContributionSerializer(DynamicModelFieldSerializer):
    source = serializers.SerializerMethodField()
    unified_document = serializers.SerializerMethodField()
    user = serializers.SerializerMethodField()
    author = serializers.SerializerMethodField()

    class Meta:
        model = Contribution
        fields = "__all__"

    def get_source(self, contribution):
        from hypothesis.serializers import DynamicHypothesisSerializer
        from paper.serializers import DynamicPaperSerializer
        from purchase.serializers import DynamicPurchaseSerializer
        from researchhub_document.serializers import DynamicPostSerializer

        serializer = None
        context = self.context
        _context_fields = context.get("rep_dcs_get_source", {})
        app_label = contribution.content_type.app_label
        model_name = contribution.content_type.name
        object_id = contribution.object_id
        model_class = contribution.content_type.model_class()
        obj = model_class.objects.get(id=object_id)

        if model_name == "paper":
            serializer = DynamicPaperSerializer(obj, context=context, **_context_fields)
        elif model_name == "thread":
            serializer = DynamicThreadSerializer(
                obj, context=context, **_context_fields
            )
        elif model_name == "comment":
            serializer = DynamicCommentSerializer(
                obj, context=context, **_context_fields
            )
        elif model_name == "reply":
            serializer = DynamicReplySerializer(obj, context=context, **_context_fields)
        elif model_name == "purchase":
            serializer = DynamicPurchaseSerializer(
                obj, context=context, **_context_fields
            )
        elif model_name == "vote":
            if app_label == "discussion":
                serializer = DynamicVoteSerializer(
                    obj, context=context, **_context_fields
                )
        elif model_name == "researchhub post":
            serializer = DynamicPostSerializer(obj, context=context, **_context_fields)
        elif model_name == "hypothesis":
            serializer = DynamicHypothesisSerializer(
                obj, context=context, **_context_fields
            )
        elif model_name == "peer review decision":
            from peer_review.serializers import DynamicPeerReviewDecisionSerializer

            serializer = DynamicPeerReviewDecisionSerializer(
                obj, context=context, **_context_fields
            )

        if serializer is not None:
            return serializer.data
        return None

    def get_unified_document(self, contribution):
        from researchhub_document.serializers import DynamicUnifiedDocumentSerializer

        context = self.context
        _context_fields = context.get("rep_dcs_get_unified_document", {})
        serializer = DynamicUnifiedDocumentSerializer(
            contribution.unified_document, context=context, **_context_fields
        )
        return serializer.data

    def get_user(self, contribution):
        context = self.context
        _context_fields = context.get("rep_dcs_get_user", {})
        serializer = DynamicUserSerializer(
            contribution.user, context=context, **_context_fields
        )
        return serializer.data

    def get_author(self, contribution):
        context = self.context
        _context_fields = context.get("rep_dcs_get_author", {})
        serializer = DynamicAuthorSerializer(
            Author.objects.get(user=contribution.user),
            context=context,
            **_context_fields
        )
        return serializer.data
