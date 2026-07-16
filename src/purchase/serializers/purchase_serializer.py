import logging

import rest_framework.serializers as serializers

from paper.serializers import BasePaperSerializer, DynamicPaperSerializer
from purchase.models import Purchase
from researchhub.serializers import DynamicModelFieldSerializer
from researchhub_document.serializers import ResearchhubPostSerializer
from researchhub_document.serializers.researchhub_post_serializer import (
    DynamicPostSerializer,
)
from user.serializers import DynamicUserSerializer

logger = logging.getLogger(__name__)


class PurchaseSerializer(serializers.ModelSerializer):
    source = serializers.SerializerMethodField()

    class Meta:
        model = Purchase
        fields = "__all__"
        read_only_fields = [
            "id",
            "purchase_hash",
            "created_date",
            "transaction_hash",
            "boost_time",
            "group",
            "updated_date",
            "rsc_usd_rate",
        ]

    def get_source(self, purchase):
        model_name = purchase.content_type.name
        if self.context.get("exclude_source", False):
            return None

        serializer = None
        object_id = purchase.object_id
        model_class = purchase.content_type.model_class()
        if model_name == "paper":
            paper = model_class.objects.get(id=object_id)
            serializer = BasePaperSerializer(paper, context=self.context)
        elif model_name == "researchhub post":
            post = model_class.objects.get(id=object_id)
            serializer = ResearchhubPostSerializer(post, context=self.context)

        if serializer is not None:
            return serializer.data

        return None


class DynamicPurchaseSerializer(DynamicModelFieldSerializer):
    content_type = serializers.SerializerMethodField()
    source = serializers.SerializerMethodField()
    user = serializers.SerializerMethodField()

    class Meta:
        model = Purchase
        fields = "__all__"

    def get_source(self, purchase):
        context = self.context
        _context_fields = context.get("pch_dps_get_source", {})
        model_name = purchase.content_type.name

        serializer = None
        item = None
        object_id = purchase.object_id
        model_class = purchase.content_type.model_class()
        try:
            if model_name == "paper":
                item = model_class.objects.get(id=object_id)
                serializer = DynamicPaperSerializer
            elif model_name == "researchhub post":
                item = model_class.objects.get(id=object_id)
                serializer = DynamicPostSerializer
            elif model_name == "rh comment model":
                from researchhub_comment.serializers import DynamicRhCommentSerializer

                item = model_class.objects.get(id=object_id)
                serializer = DynamicRhCommentSerializer
            elif model_name == "fundraise":
                item = model_class.objects.get(id=object_id)
                serializer = None

            if serializer is not None:
                data = serializer(item, context=context, **_context_fields).data
                return data
        except Exception:
            logger.exception("Failed to get source for purchase")

        return None

    def get_user(self, purchase):
        context = self.context
        _context_fields = context.get("pch_dps_get_user", {})
        serializer = DynamicUserSerializer(
            purchase.user, context=context, **_context_fields
        )
        return serializer.data

    def get_content_type(self, purchase):
        content = purchase.content_type
        return {"app_label": content.app_label, "model": content.model}
