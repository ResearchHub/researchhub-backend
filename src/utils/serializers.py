import rest_framework.serializers as serializers


class EmptySerializer(serializers.Serializer):
    class Meta:
        model = None


def get_model_serializer(model_arg):
    class GenericSerializer(serializers.ModelSerializer):
        class Meta:
            model = model_arg
            fields = '__all__'

    return GenericSerializer
