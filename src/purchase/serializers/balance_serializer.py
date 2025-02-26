import rest_framework.serializers as serializers
from django.contrib.contenttypes.models import ContentType

from purchase.models import Balance, Purchase
from reputation.models import Bounty, Distribution, Withdrawal
from reputation.serializers import (
    BountySerializer,
    DistributionSerializer,
    WithdrawalSerializer,
)
from researchhub_document.models import ResearchhubUnifiedDocument
from utils import sentry

from .purchase_serializer import PurchaseSerializer


class BalanceSourceRelatedField(serializers.RelatedField):
    """
    A custom field to use for the `source` generic relationship.
    """

    def to_representation(self, value):
        """
        Serialize tagged objects to a simple textual representation.
        """
        if isinstance(value, Distribution):
            return DistributionSerializer(value, context={"exclude_stats": True}).data
        elif isinstance(value, Purchase):
            return PurchaseSerializer(value, context={"exclude_stats": True}).data
        elif isinstance(value, Withdrawal):
            return WithdrawalSerializer(value, context={"exclude_stats": True}).data
        elif isinstance(value, Bounty):
            return BountySerializer(value).data

        sentry.log_info("No representation for " + str(value))
        return None


class BalanceSerializer(serializers.ModelSerializer):
    source = BalanceSourceRelatedField(read_only=True)
    readable_content_type = serializers.SerializerMethodField()
    content_title = serializers.SerializerMethodField()
    content_id = serializers.SerializerMethodField()
    content_slug = serializers.SerializerMethodField()

    def get_content_title(self, balance):
        if balance.content_type == ContentType.objects.get_for_model(Bounty):
            source_item = balance.source.item
            if isinstance(source_item, ResearchhubUnifiedDocument):
                return source_item.get_document().title
            return None

    def get_content_id(self, balance):
        if balance.content_type == ContentType.objects.get_for_model(Bounty):
            source_item = balance.source.item
            if isinstance(source_item, ResearchhubUnifiedDocument):
                return source_item.get_document().id
            return None

    def get_content_slug(self, balance):
        if balance.content_type == ContentType.objects.get_for_model(Bounty):
            source_item = balance.source.item
            if isinstance(source_item, ResearchhubUnifiedDocument):
                return source_item.get_document().slug
            return None

    def get_readable_content_type(self, balance):
        return balance.content_type.model

    class Meta:
        model = Balance
        fields = "__all__"
