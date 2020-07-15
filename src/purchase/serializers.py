import datetime
import pandas as pd

import rest_framework.serializers as serializers

from django.db.models import Count, Q

from purchase.models import Purchase, AggregatePurchase
from analytics.serializers import PaperEventSerializer
from paper.serializers import BasePaperSerializer
from analytics.models import INTERACTIONS


class PurchaseSerializer(serializers.ModelSerializer):
    source = serializers.SerializerMethodField()
    end_date = serializers.SerializerMethodField()
    stats = serializers.SerializerMethodField()

    class Meta:
        model = Purchase
        fields = '__all__'

    def get_source(self, purchase):
        model_name = purchase.content_type.name
        if self.context.get('exclude_source', False):
            return None

        if model_name == 'paper':
            Paper = purchase.content_type.model_class()
            paper = Paper.objects.get(id=purchase.object_id)
            serializer = BasePaperSerializer(paper, context=self.context)
            data = serializer.data
            return data
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
        total_views = purchase.purchases.filter(
            paper__event__interaction=INTERACTIONS['VIEW']
        ).distinct().count()
        total_clicks = purchase.purchases.filter(
            paper__event__interaction=INTERACTIONS['CLICK']
        ).distinct().count()
        # stats = purchase.purchases.annotate(
        #     total_views=Count(
        #         'paper__event',
        #         filter=Q(paper__event__interaction=INTERACTIONS['VIEW']),
        #         distinct=True
        #     ),
        #     total_clicks=Count(
        #         'paper__event',
        #         filter=Q(paper__event__interaction=INTERACTIONS['CLICK']),
        #         distinct=True
        #     )
        # ).values(
        #     'total_views',
        #     'total_clicks'
        # )
        stats = {
            'total_views': total_views,
            'total_clicks': total_clicks
        }
        return stats
