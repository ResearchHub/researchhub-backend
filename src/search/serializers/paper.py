from rest_framework import serializers
from django_elasticsearch_dsl_drf.serializers import DocumentSerializer

from search.documents.paper import PaperDocument


class PaperDocumentSerializer(DocumentSerializer):
    highlight = serializers.SerializerMethodField()

    class Meta(object):
        document = PaperDocument
        fields = [
            'id',
            'title',
            'doi',
            'uploaded_date',
            'paper_publish_date',
            'authors',
            'tagline',
            'score',
            'votes'
        ]

    def get_highlight(self, obj):
        if hasattr(obj.meta, 'highlight'):
            return obj.meta.highlight.__dict__['_d_']
        return {}
