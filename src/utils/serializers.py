from rest_framework.serializers import (
    ModelSerializer,
)


def get_model_serializer(model_arg):
    class GenericSerializer(ModelSerializer):
        class Meta:
            model = model_arg
            fields = "__all__"

    return GenericSerializer
