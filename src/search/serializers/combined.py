from django.utils.html import strip_tags
from rest_framework import serializers

from search.serializers import (
    HubDocumentSerializer,
    PaperDocumentSerializer,
    PersonDocumentSerializer,
    PostDocumentSerializer,
)


class CombinedSerializer(serializers.BaseSerializer):
    index_serializers = {
        "person": PersonDocumentSerializer,
        "hub": HubDocumentSerializer,
        "paper": PaperDocumentSerializer,
        "post": PostDocumentSerializer,
        "journal": HubDocumentSerializer,
    }

    def __init__(self, *args, **kwargs):
        many = kwargs.pop("many", True)
        super(CombinedSerializer, self).__init__(many=many, *args, **kwargs)

    def to_representation(self, obj):
        return self.get_hit(obj)

    def get_hit(self, obj):
        index_serializers = getattr(self, "index_serializers")
        if obj.meta.index in index_serializers:
            serializer = index_serializers[obj.meta.index]
            hit = serializer(obj).data

        return hit
