from rest_framework.serializers import ModelSerializer, SerializerMethodField

from hub.serializers import DynamicHubSerializer, SimpleHubSerializer
from paper.serializers import DynamicPaperSerializer, PaperSerializer
from reputation.models import Bounty
from researchhub.serializers import DynamicModelFieldSerializer
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import (
    DISCUSSION,
    ELN,
    HYPOTHESIS,
    PAPER,
    QUESTION,
)
from researchhub_document.serializers import (
    DynamicPostSerializer,
    ResearchhubPostSerializer,
)
from user.serializers import DynamicUserSerializer, UserSerializer


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

    def get_access_group(self, instance):
        # TODO: calvinhlee - access_group is for ELN. Work on this later
        return None

    def get_created_by(self, instance):
        return UserSerializer(instance.created_by, read_only=True).data

    def get_documents(self, instance):
        from hypothesis.serializers.hypothesis_serializer import HypothesisSerializer

        context = self.context
        doc_type = instance.document_type
        if doc_type in [DISCUSSION, ELN, QUESTION]:
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
    documents = SerializerMethodField()
    created_by = SerializerMethodField()
    access_group = SerializerMethodField()
    hubs = SerializerMethodField()
    reviews = SerializerMethodField()
    featured = SerializerMethodField()
    bounties = SerializerMethodField()

    class Meta:
        model = ResearchhubUnifiedDocument
        fields = "__all__"

    def get_featured(self, unified_doc):
        hub_id = self.context.get("hub_id", 0)
        if hub_id is not None:
            if hub_id == 0:
                hub_id = None
            return unified_doc.featured_in_hubs.filter(hub_id=hub_id).exists()

    def get_documents(self, unified_doc):
        context = self.context
        _context_fields = context.get("doc_duds_get_documents", {})
        doc_type = unified_doc.document_type

        if doc_type in [DISCUSSION, ELN, QUESTION]:
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
        serializer = DynamicHubSerializer(
            unified_doc.hubs, many=True, context=context, **_context_fields
        )
        return serializer.data

    def get_reviews(self, unified_doc):
        return unified_doc.get_review_details()
        # context = self.context
        # get_reviews = context.get("doc_duds_get_reviews", None)
        # if get_reviews:
        #     return unified_doc.get_review_details()
        # return None

    def get_bounties(self, unified_doc):
        doc = unified_doc.get_document()
        if not hasattr(doc, "threads"):
            return None

        thread_ids = doc.threads.values_list("id")
        bounties = Bounty.objects.filter(
            item_content_type__model="thread",
            item_object_id__in=thread_ids,
            status=Bounty.OPEN,
        ).values_list("amount", flat=True)
        return bounties
