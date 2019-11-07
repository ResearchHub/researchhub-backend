from rest_framework import serializers

from search.serializers import (
    AuthorDocumentSerializer,
    HubDocumentSerializer,
    PaperDocumentSerializer,
    ThreadDocumentSerializer,
    UniversityDocumentSerializer
)


class CombinedSerializer(serializers.BaseSerializer):
    index_serializers = {
        'author': AuthorDocumentSerializer,
        'discussion_thread': ThreadDocumentSerializer,
        'hub': HubDocumentSerializer,
        'paper': PaperDocumentSerializer,
        'university': UniversityDocumentSerializer,
    }

    def __init__(self, *args, **kwargs):
        many = kwargs.pop('many', True)
        super(CombinedSerializer, self).__init__(many=many, *args, **kwargs)

    def to_representation(self, obj):
        return self.get_hit(obj)

    def get_hit(self, obj):
        index_serializers = getattr(self, 'index_serializers')
        if obj.meta.index in index_serializers:
            serializer = index_serializers[obj.meta.index]
            hit = serializer(obj).data
            if hit:
                hit['meta'] = obj.meta.to_dict()
        return hit
