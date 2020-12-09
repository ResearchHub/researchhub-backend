import datetime
import pandas as pd

import rest_framework.serializers as serializers

from django.db.models import (
    Sum,
    Value,
    F,
    Func,
    CharField,
    Count,
    IntegerField
)
from django.db.models.functions import Cast

from purchase.models import Purchase, AggregatePurchase, Wallet, Support
from analytics.serializers import PaperEventSerializer
from paper.serializers import BasePaperSerializer
from summary.serializers import SummarySerializer
from bullet_point.serializers import BulletPointSerializer
from discussion.serializers import (
    ThreadSerializer,
    CommentSerializer,
    ReplySerializer
)
from analytics.models import PaperEvent, INTERACTIONS


class WalletSerializer(serializers.ModelSerializer):
    class Meta:
        model = Wallet
        fields = '__all__'


class SupportSerializer(serializers.ModelSerializer):
    class Meta:
        model = Support
        fields = '__all__'


class PurchaseSerializer(serializers.ModelSerializer):
    source = serializers.SerializerMethodField()
    end_date = serializers.SerializerMethodField()
    stats = serializers.SerializerMethodField()
    content_type = serializers.SerializerMethodField()

    class Meta:
        model = Purchase
        fields = '__all__'

    def get_source(self, purchase):
        model_name = purchase.content_type.name
        if self.context.get('exclude_source', False):
            return None

        serializer = None
        object_id = purchase.object_id
        model_class = purchase.content_type.model_class()
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

    def get_stats(self, purchase):
        if self.context.get('exclude_stats', False):
            return None

        views = []
        clicks = []
        total_views = 0
        total_clicks = 0
        Paper = purchase.content_type.model_class()
        paper = Paper.objects.get(id=purchase.object_id)
        events = paper.events.filter(
            user=purchase.user
        ).order_by(
            '-created_date'
        )

        serializer = PaperEventSerializer(events, many=True)
        data = serializer.data

        if data:
            event_df = pd.DataFrame(data)
            event_df['created_date'] = pd.to_datetime(event_df['created_date'])

            grouped_data = event_df.groupby(
                pd.Grouper(key='created_date', freq='D')
            ).apply(
                self._aggregate_stats,
            ).reset_index()

            trunc_date = grouped_data['created_date'].dt.strftime('%Y-%m-%d')
            grouped_data['created_date'] = trunc_date
            views_index = ['created_date', 'views']
            clicks_index = ['created_date', 'clicks']
            views = grouped_data[views_index].to_dict('records')
            clicks = grouped_data[clicks_index].to_dict('records')
            total_views = grouped_data.views.sum()
            total_clicks = grouped_data.clicks.sum()

        stats = {
            'views': views,
            'clicks': clicks,
            'total_views': total_views,
            'total_clicks': total_clicks
        }
        return stats

    def _aggregate_stats(self, row):
        index = ('views', 'clicks')
        views = len(row[row['interaction'] == 'VIEW'])
        clicks = len(row[row['interaction'] == 'CLICK'])
        return pd.Series((views, clicks), index=index)

    def get_content_type(self, purchase):
        content = purchase.content_type
        return {'app_label': content.app_label, 'model': content.model}


class AggregatePurchaseSerializer(serializers.ModelSerializer):
    source = serializers.SerializerMethodField()
    purchases = serializers.SerializerMethodField()
    stats = serializers.SerializerMethodField()

    class Meta:
        model = AggregatePurchase
        fields = '__all__'

    def get_source(self, purchase):
        model_name = purchase.content_type.name
        if model_name == 'paper':
            Paper = purchase.content_type.model_class()
            paper = Paper.objects.get(id=purchase.object_id)
            serializer = BasePaperSerializer(paper, context=self.context)
            data = serializer.data
            return data
        return None

    def get_purchases(self, purchase):
        purchases = purchase.purchases
        self.context['exclude_source'] = True
        self.context['exclude_stats'] = True
        serializer = PurchaseSerializer(
            purchases,
            context=self.context,
            many=True
        )
        data = serializer.data
        return data

    def get_stats(self, purchase):
        distinct_views = purchase.purchases.filter(
            paper__event__interaction=INTERACTIONS['VIEW'],
            paper__event__paper_is_boosted=True
        ).distinct()
        distinct_clicks = purchase.purchases.filter(
            paper__event__interaction=INTERACTIONS['CLICK'],
            paper__event__paper_is_boosted=True
        ).distinct()

        total_views = distinct_views.values('paper__event').count()
        total_clicks = distinct_clicks.values('paper__event').count()
        total_amount = sum(
            map(float, purchase.purchases.values_list('amount', flat=True))
        )

        distinct_views_ids = distinct_views.values_list(
            'paper__event',
            flat=True
        )
        views = PaperEvent.objects.filter(id__in=distinct_views_ids).values(
            date=Func(
                F('created_date'),
                Value('YYYY-MM-DD'),
                function='to_char',
                output_field=CharField()
            )
        ).annotate(
            views=Count('date')
        )

        distinct_clicks_ids = distinct_clicks.values_list(
            'paper__event',
            flat=True
        )
        clicks = PaperEvent.objects.filter(id__in=distinct_clicks_ids).values(
            date=Func(
                F('created_date'),
                Value('YYYY-MM-DD'),
                function='to_char',
                output_field=CharField()
            )
        ).annotate(
            clicks=Count('date')
        )

        created_date = purchase.created_date

        max_boost = purchase.purchases.annotate(
            amount_as_int=Cast('amount', IntegerField())
        ).aggregate(
            sum=Sum('amount_as_int')
        ).get('sum', 0)

        timedelta = datetime.timedelta(days=int(max_boost))
        end_date = (created_date + timedelta).isoformat()

        stats = {
            'views': views,
            'clicks': clicks,
            'total_views': total_views,
            'total_clicks': total_clicks,
            'total_amount': total_amount,
            'end_date': end_date
        }
        return stats
