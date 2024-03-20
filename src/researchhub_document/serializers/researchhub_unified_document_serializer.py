import copy

from rest_framework.serializers import ModelSerializer, SerializerMethodField

from hub.serializers import DynamicHubSerializer, SimpleHubSerializer
from paper.serializers import DynamicPaperSerializer, PaperSerializer
from prediction_market.models import PredictionMarket
from prediction_market.serializers import DynamicPredictionMarketSerializer
from researchhub.serializers import DynamicModelFieldSerializer
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import (
    HYPOTHESIS,
    PAPER,
    RESEARCHHUB_POST_DOCUMENT_TYPES,
)
from researchhub_document.serializers import (
    DynamicPostSerializer,
    ResearchhubPostSerializer,
)
from tag.serializers import DynamicConceptSerializer, SimpleConceptSerializer
from user.serializers import DynamicUserSerializer, UserSerializer
from utils.sentry import log_error


class ResearchhubUnifiedDocumentSerializer(ModelSerializer):
    class Meta(object):
        model = ResearchhubUnifiedDocument
        fields = [
            "access_group",
            "created_by",
            "document_type",
            "documents",
            "hot_score",
            "hubs",
            "is_removed",
            "score",
        ]
        read_only_fields = [
            "access_group",
            "created_by",
            "document_type",
            "documents",
            "hot_score",
            "hubs",
            "hypothesis",
            "id",
            "is_removed",
            "is_public",
            "published_date",
            "paper",
            "posts",
            "score",
        ]

    access_group = SerializerMethodField(method_name="get_access_group")
    created_by = SerializerMethodField(method_name="get_created_by")
    documents = SerializerMethodField(method_name="get_documents")
    hubs = SimpleHubSerializer(
        many=True, required=False, context={"no_subscriber_info": True}
    ).data
    concepts = SimpleConceptSerializer(many=True, required=False).data

    def get_access_group(self, instance):
        # TODO: calvinhlee - access_group is for ELN. Work on this later
        return None

    def get_created_by(self, instance):
        return UserSerializer(instance.created_by, read_only=True).data

    def get_documents(self, instance):
        from hypothesis.serializers.hypothesis_serializer import HypothesisSerializer

        context = self.context
        doc_type = instance.document_type
        if doc_type in RESEARCHHUB_POST_DOCUMENT_TYPES:
            return ResearchhubPostSerializer(
                instance.posts, many=True, context=context
            ).data
        elif doc_type in [HYPOTHESIS]:
            return HypothesisSerializer(instance.hypothesis, context=context).data
        else:
            return PaperSerializer(instance.paper, context=context).data


class ContributionUnifiedDocumentSerializer(ResearchhubUnifiedDocumentSerializer):
    access_group = None
    hubs = None

    def get_documents(self, instance):
        return None


class DynamicUnifiedDocumentSerializer(DynamicModelFieldSerializer):
    bounties = SerializerMethodField()
    documents = SerializerMethodField()
    document_filter = SerializerMethodField()
    created_by = SerializerMethodField()
    access_group = SerializerMethodField()
    hubs = SerializerMethodField()
    reviews = SerializerMethodField()
    concepts = SerializerMethodField()
    prediction_market = SerializerMethodField()
    fundraise = SerializerMethodField()
    recommendation_metadata = SerializerMethodField()

    class Meta:
        model = ResearchhubUnifiedDocument
        fields = "__all__"

    def get_recommendation_metadata(self, unified_doc):
        if hasattr(unified_doc, "recommendation_metadata"):
            return unified_doc.recommendation_metadata

        return None

    def get_bounties(self, unified_doc):
        from reputation.serializers import DynamicBountySerializer

        context = self.context
        _context_fields = context.get("doc_duds_get_bounties", {})
        _filter_fields = _context_fields.get("_filter_fields", {})
        if unified_doc.related_bounties.exists():
            serializer = DynamicBountySerializer(
                unified_doc.related_bounties.filter(**_filter_fields),
                many=True,
                context=context,
                **_context_fields,
            )
            return serializer.data
        return []

    def get_documents(self, unified_doc):
        context = self.context
        _context_fields = context.get("doc_duds_get_documents", {})
        context["unified_document"] = unified_doc
        doc_type = unified_doc.document_type
        try:
            if doc_type in RESEARCHHUB_POST_DOCUMENT_TYPES:
                return DynamicPostSerializer(
                    unified_doc.posts, many=True, context=context, **_context_fields
                ).data
            elif doc_type == HYPOTHESIS:
                from hypothesis.serializers import DynamicHypothesisSerializer

                return DynamicHypothesisSerializer(
                    unified_doc.hypothesis, context=context, **_context_fields
                ).data
            elif doc_type == PAPER:
                return DynamicPaperSerializer(
                    unified_doc.paper, context=context, **_context_fields
                ).data
            else:
                return None
        except Exception as e:
            log_error(e, message=f"Related unified doc: {unified_doc}")
            return None

    def get_document_filter(self, unified_doc):
        from researchhub_document.serializers import DynamicDocumentFilterSerializer

        context = self.context
        _context_fields = context.get("doc_duds_get_document_filter", {})
        serializer = DynamicDocumentFilterSerializer(
            unified_doc.document_filter, context=context, **_context_fields
        )
        return serializer.data

    def get_created_by(self, unified_doc):
        context = self.context
        _context_fields = context.get("doc_duds_get_created_by", {})
        serializer = DynamicUserSerializer(
            unified_doc.created_by, context=context, **_context_fields
        )
        return serializer.data

    def get_access_group(self, unified_doc):
        # TODO: calvinhlee - access_group is for ELN. Work on this later
        return

    def get_hubs(self, unified_doc):
        context = self.context
        _context_fields = context.get("doc_duds_get_hubs", {})
        _filter_fields = copy.deepcopy(_context_fields.get("_filter_fields", {}))
        _order_fields = copy.deepcopy(_context_fields.get("_order_fields", []))

        # Special logic here to order only papers' hubs
        # based off their concept's relevancy score
        # since posts have hubs but no attached concepts
        if "concept__through_unified_document__unified_document" in _filter_fields:
            if unified_doc.document_type == PAPER:
                _filter_fields[
                    "concept__through_unified_document__unified_document"
                ] = unified_doc
            else:
                _filter_fields.pop(
                    "concept__through_unified_document__unified_document"
                )
                _order_fields.remove(
                    "-concept__through_unified_document__relevancy_score"
                )

        hubs = unified_doc.hubs
        if _filter_fields:
            filtered_hubs = hubs.filter(**_filter_fields)
            if filtered_hubs.exists():
                hubs = filtered_hubs
            else:
                _order_fields = []
        if _order_fields:
            hubs = hubs.order_by(*_order_fields)

        serializer = DynamicHubSerializer(
            hubs, many=True, context=context, **_context_fields
        )
        return serializer.data

    def get_reviews(self, unified_doc):
        if not unified_doc.reviews.exists():
            return {"avg": 0, "count": 0}
        return unified_doc.get_review_details()

    def get_concepts(self, unified_doc):
        context = self.context
        _context_fields = context.get("doc_duds_get_concepts", {})
        serializer = DynamicConceptSerializer(
            unified_doc.concepts,
            many=True,
            required=False,
            context=context,
            **_context_fields,
        )
        return serializer.data

    def get_prediction_market(self, unified_doc):
        """
        Returns details of the prediction market for paper replicability.
        We assume there's only one prediction market for the `unified_doc`
        """
        if not unified_doc.prediction_markets.exists():
            return None

        prediction_market = unified_doc.prediction_markets.filter(
            prediction_type=PredictionMarket.REPLICATION_PREDICTION
        ).first()
        if not prediction_market:
            return None

        serializer = DynamicPredictionMarketSerializer(prediction_market)
        return serializer.data

    def get_fundraise(self, unified_doc):
        if not unified_doc.fundraises.exists():
            return None

        fundraiser = unified_doc.fundraises.first()
        if not fundraiser:
            return None

        from purchase.serializers import DynamicFundraiseSerializer

        context = self.context
        _context_fields = context.get("doc_duds_get_fundraise", {})
        serializer = DynamicFundraiseSerializer(
            fundraiser, context=context, **_context_fields
        )
        return serializer.data
