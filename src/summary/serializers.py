import rest_framework.serializers as rest_framework_serializers

from .models import Summary


class SummarySerializer(rest_framework_serializers.ModelSerializer):

    class Meta:
        fields = '__all__'
        model = Summary
