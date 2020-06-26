import datetime
import pandas as pd

import rest_framework.serializers as serializers

from purchase.models import Purchase
from analytics.serializers import PaperEventSerializer
from paper.serializers import BasePaperSerializer


class PurchaseSerializer(serializers.ModelSerializer):
    source = serializers.SerializerMethodField()
    end_date = serializers.SerializerMethodField()
    stats = serializers.SerializerMethodField()

    class Meta:
        model = Purchase
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
        Paper = purchase.content_type.model_class()
        paper = Paper.objects.get(id=purchase.object_id)
        events = paper.events.filter(
            user=purchase.user
        ).order_by(
            '-created_date'
        )

        serializer = PaperEventSerializer(events, many=True)
        data = serializer.data
        events_df = pd.DataFrame(data)
        events_df['created_date'] = pd.to_datetime(events_df['created_date'])

        grouped_data = events_df.groupby(
            pd.Grouper(key='created_date', freq='D')
        ).apply(
            self._aggregate_stats,
        ).reset_index()
        truncated_date = grouped_data['created_date'].dt.strftime('%Y-%m-%d')
        grouped_data['created_date'] = truncated_date
        grouped_data_dict = grouped_data.to_dict('records')

        return grouped_data_dict

    def _aggregate_stats(self, row):
        index = ('views', 'clicks')
        views = len(row[row['interaction'] == 'VIEW'])
        clicks = len(row[row['interaction'] == 'CLICK'])
        return pd.Series((views, clicks), index=index)
