import rest_framework.serializers as serializers

from .models import Withdrawl

class WithdrawlSerializer(serializers.ModelSerializer):
    class Meta:
        fields = '__all__'
        model = Withdrawl
