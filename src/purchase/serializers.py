import datetime

import pandas as pd
import rest_framework.serializers as serializers
from django.contrib.contenttypes.models import ContentType
from django.db.models import CharField, Count, F, Func, IntegerField, Sum, Value
from django.db.models.functions import Cast

from analytics.models import INTERACTIONS, PaperEvent
from analytics.serializers import PaperEventSerializer
from bullet_point.serializers import BulletPointSerializer
from discussion.models import Thread
from discussion.serializers import (
    CommentSerializer,
    DynamicCommentSerializer,
    DynamicReplySerializer,
    DynamicThreadSerializer,
    ReplySerializer,
    ThreadSerializer,
)
from paper.serializers import BasePaperSerializer, DynamicPaperSerializer
from purchase.models import (
    AggregatePurchase,
    Balance,
    Purchase,
    RscExchangeRate,
    Support,
    Wallet,
)
from reputation.models import Bounty, Distribution, Withdrawal
from reputation.serializers import (
    BountySerializer,
    DistributionSerializer,
    WithdrawalSerializer,
)
from researchhub.serializers import DynamicModelFieldSerializer
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.serializers import ResearchhubPostSerializer
from researchhub_document.serializers.researchhub_post_serializer import (
    DynamicPostSerializer,
)
from summary.serializers import SummarySerializer
from user.serializers import DynamicUserSerializer
from utils import sentry


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
            elif isinstance(source_item, Thread):
                return source_item.unified_document.get_document().title
            return None

    def get_content_id(self, balance):
        if balance.content_type == ContentType.objects.get_for_model(Bounty):
            source_item = balance.source.item
            if isinstance(source_item, ResearchhubUnifiedDocument):
                return source_item.get_document().id
            elif isinstance(source_item, Thread):
                return source_item.unified_document.get_document().id
            return None

    def get_content_slug(self, balance):
        if balance.content_type == ContentType.objects.get_for_model(Bounty):
            source_item = balance.source.item
            if isinstance(source_item, ResearchhubUnifiedDocument):
                return source_item.get_document().slug
            elif isinstance(source_item, Thread):
                return source_item.unified_document.get_document().slug
            return None

    def get_readable_content_type(self, balance):
        return balance.content_type.model

    class Meta:
        model = Balance
        fields = "__all__"


class WalletSerializer(serializers.ModelSerializer):
    class Meta:
        model = Wallet
        fields = "__all__"


class SupportSerializer(serializers.ModelSerializer):
    class Meta:
        model = Support
        fields = "__all__"


class PurchaseSerializer(serializers.ModelSerializer):
    source = serializers.SerializerMethodField()
    end_date = serializers.SerializerMethodField()

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
        elif model_name == "thread":
            thread = model_class.objects.get(id=object_id)
            serializer = ThreadSerializer(thread, context=self.context)
        elif model_name == "comment":
            comment = model_class.objects.get(id=object_id)
            serializer = CommentSerializer(comment, context=self.context)
        elif model_name == "reply":
            reply = model_class.objects.get(id=object_id)
            serializer = ReplySerializer(reply, context=self.context)
        elif model_name == "summary":
            summary = model_class.objects.get(id=object_id)
            serializer = SummarySerializer(summary, context=self.context)
        elif model_name == "bullet_point":
            bulletpoint = model_class.objects.get(id=object_id)
            serializer = BulletPointSerializer(bulletpoint, context=self.context)

        if serializer is not None:
            return serializer.data

        return None

    def get_end_date(self, purchase):
        status = purchase.paid_status
        purchase_method = purchase.purchase_method

        if purchase_method == Purchase.ON_CHAIN and status != Purchase.PAID:
            return None

        created_date = purchase.created_date
        timedelta = datetime.timedelta(days=int(purchase.amount))
        end_date = created_date + timedelta
        return end_date.isoformat()


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
            elif model_name == "thread":
                item = model_class.objects.get(id=object_id)
                serializer = DynamicThreadSerializer
            elif model_name == "comment":
                item = model_class.objects.get(id=object_id)
                serializer = DynamicCommentSerializer
            elif model_name == "reply":
                item = model_class.objects.get(id=object_id)
                serializer = DynamicReplySerializer
            elif model_name == "rh comment model":
                from researchhub_comment.serializers import DynamicRhCommentSerializer

                item = model_class.objects.get(id=object_id)
                serializer = DynamicRhCommentSerializer
            elif model_name == "summary":
                item = model_class.objects.get(id=object_id)
                serializer = None
            elif model_name == "bullet_point":
                item = model_class.objects.get(id=object_id)
                serializer = None

            if serializer is not None:
                data = serializer(item, context=context, **_context_fields).data
                return data
        except Exception as e:
            print(e)
            sentry.log_error(e)

        return None

    def get_user(self, purchase):
        context = self.context
        _context_fields = context.get("pch_dps_get_user", {})
        serializer = DynamicUserSerializer(
            purchase.user, context=context, **_context_fields
        )
        return serializer.data

    def get_end_date(self, purchase):
        status = purchase.paid_status
        purchase_method = purchase.purchase_method

        if purchase_method == Purchase.ON_CHAIN and status != Purchase.PAID:
            return None

        created_date = purchase.created_date
        timedelta = datetime.timedelta(days=int(purchase.amount))
        end_date = created_date + timedelta
        return end_date.isoformat()

    def get_content_type(self, purchase):
        content = purchase.content_type
        return {"app_label": content.app_label, "model": content.model}


class AggregatePurchaseSerializer(serializers.ModelSerializer):
    source = serializers.SerializerMethodField()
    purchases = serializers.SerializerMethodField()
    stats = serializers.SerializerMethodField()

    class Meta:
        model = AggregatePurchase
        fields = "__all__"

    def get_source(self, purchase):
        model_name = purchase.content_type.name
        if model_name == "paper":
            Paper = purchase.content_type.model_class()
            paper = Paper.objects.get(id=purchase.object_id)
            serializer = BasePaperSerializer(paper, context=self.context)
            data = serializer.data
            return data
        elif model_name == "researchhub post":
            Post = purchase.content_type.model_class()
            post = Post.objects.get(id=purchase.object_id)
            serializer = ResearchhubPostSerializer(post, context=self.context)
            data = serializer.data
            return data
        return None

    def get_purchases(self, purchase):
        purchases = purchase.purchases
        self.context["exclude_source"] = True
        self.context["exclude_stats"] = True
        serializer = PurchaseSerializer(purchases, context=self.context, many=True)
        data = serializer.data
        return data

    def get_stats(self, purchase):
        distinct_views = purchase.purchases.filter(
            paper__event__interaction=INTERACTIONS["VIEW"],
            paper__event__paper_is_boosted=True,
        ).distinct()
        distinct_clicks = purchase.purchases.filter(
            paper__event__interaction=INTERACTIONS["CLICK"],
            paper__event__paper_is_boosted=True,
        ).distinct()

        total_views = distinct_views.values("paper__event").count()
        total_clicks = distinct_clicks.values("paper__event").count()
        total_amount = sum(
            map(float, purchase.purchases.values_list("amount", flat=True))
        )

        distinct_views_ids = distinct_views.values_list("paper__event", flat=True)
        views = (
            PaperEvent.objects.filter(id__in=distinct_views_ids)
            .values(
                date=Func(
                    F("created_date"),
                    Value("YYYY-MM-DD"),
                    function="to_char",
                    output_field=CharField(),
                )
            )
            .annotate(views=Count("date"))
        )

        distinct_clicks_ids = distinct_clicks.values_list("paper__event", flat=True)
        clicks = (
            PaperEvent.objects.filter(id__in=distinct_clicks_ids)
            .values(
                date=Func(
                    F("created_date"),
                    Value("YYYY-MM-DD"),
                    function="to_char",
                    output_field=CharField(),
                )
            )
            .annotate(clicks=Count("date"))
        )

        created_date = purchase.created_date

        max_boost = (
            purchase.purchases.annotate(amount_as_int=Cast("amount", IntegerField()))
            .aggregate(sum=Sum("amount_as_int"))
            .get("sum", 0)
            or 0
        )

        timedelta = datetime.timedelta(days=int(max_boost))
        end_date = (created_date + timedelta).isoformat()

        stats = {
            "views": views,
            "clicks": clicks,
            "total_views": total_views,
            "total_clicks": total_clicks,
            "total_amount": total_amount,
            "end_date": end_date,
        }
        return stats


class RscExchangeRateSerializer(serializers.ModelSerializer):
    class Meta:
        model = RscExchangeRate
        fields = "__all__"
