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

    # def create(self, validated_data):
    #     import pdb

    #     pdb.set_trace()
    #     print("?????")

    # def update(self, project_instance, validated_data):
    #     import pdb

    #     pdb.set_trace()

    """ ----- Serializer Methods -----"""

    """ ----- Private Methods -----"""
