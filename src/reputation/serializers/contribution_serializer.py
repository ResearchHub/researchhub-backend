from rest_framework import serializers

from bullet_point.serializers import BulletPointSerializer, BulletPointVoteSerializer
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
from reputation.models import Contribution
from reputation.serializers import (
    DynamicBountySerializer,
    DynamicBountySolutionSerializer,
)
from researchhub.serializers import DynamicModelFieldSerializer
from summary.serializers import SummarySerializer, SummaryVoteSerializer
from user.models import Author
from user.serializers import (
    DynamicAuthorSerializer,
    DynamicUserSerializer,
    UserSerializer,
)


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
        from prediction_market.serializers import DynamicPredictionMarketVoteSerializer
        from purchase.serializers import DynamicPurchaseSerializer
        from researchhub_comment.serializers import DynamicRhCommentSerializer
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
        elif model_name == "rh comment model":
            serializer = DynamicRhCommentSerializer(
                obj, context=context, **_context_fields
            )
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
        elif model_name == "bounty":
            serializer = DynamicBountySerializer(
                obj, context=context, **_context_fields
            )
        elif model_name == "bounty solution":
            serializer = DynamicBountySolutionSerializer(
                obj, context=context, **_context_fields
            )
        elif model_name == "prediction market vote":
            serializer = DynamicPredictionMarketVoteSerializer(
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
