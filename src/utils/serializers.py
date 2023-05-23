from rest_framework.serializers import (
    CurrentUserDefault,
    HiddenField,
    ModelSerializer,
    Serializer,
)


class EmptySerializer(Serializer):
    class Meta:
        model = None


def get_model_serializer(model_arg):
    class GenericSerializer(ModelSerializer):
        class Meta:
            model = model_arg
            fields = "__all__"

    return GenericSerializer


class DefaultAuthenticatedSerializer(ModelSerializer):
    # HiddenField doesn't update instance if the field is empty
    created_by = HiddenField(default=CurrentUserDefault())
    updated_by = HiddenField(default=CurrentUserDefault())

    class Meta:
        abstract = True
