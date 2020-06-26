import datetime

import rest_framework.serializers as serializers

from purchase.models import Purchase
from paper.serializers import BasePaperSerializer


class PurchaseSerializer(serializers.ModelSerializer):
    source = serializers.SerializerMethodField()
    end_date = serializers.SerializerMethodField()

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
