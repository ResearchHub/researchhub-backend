import rest_framework.serializers as serializers

class EmptySerializer(serializers.Serializer):
    class Meta:
        model = None

