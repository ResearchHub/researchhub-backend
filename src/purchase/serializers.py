import rest_framework.serializers as serializers

from purchase.models import Purchase
from paper.serializers import BasePaperSerializer


class PurchaseSerializer(serializers.ModelSerializer):
    source = serializers.SerializerMethodField()

    class Meta:
        model = Purchase
        fields = '__all__'

    def get_source(self, purchase):
        model_name = purchase.content_type.name
        if model_name == 'paper':
            Paper = purchase.content_type.model_class()
            paper = Paper.objects.get(id=purchase.object_id)
            serializer = BasePaperSerializer(paper)
            data = serializer.data
            return data
        return None
