import rest_framework.serializers as serializers

from purchase.models import Purchase


class PurchaseSerializer(serializers.ModelSerializer):
    purchase_hash = serializers.SerializerMethodField()

    class Meta:
        model = Purchase
        fields = '__all__'

    def get_purchase_hash(self, paper):
        return hash(paper)
