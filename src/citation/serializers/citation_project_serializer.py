from rest_framework.serializers import (
    ModelSerializer,
    HiddenField,
    CurrentUserDefault,
)

from citation.models import CitationProject


class CitationProjectSerializer(ModelSerializer):
    # HiddenField doesn't update instance if the field is not empty
    created_by = HiddenField(default=CurrentUserDefault())
    updated_by = HiddenField(default=CurrentUserDefault())

    class Meta:
        model = CitationProject
        fields = "__all__"

    """ ----- Django Method Overrides -----"""

    """ ----- Serializer Methods -----"""

    """ ----- Private Methods -----"""
