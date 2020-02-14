from django_elasticsearch_dsl_drf.serializers import DocumentSerializer
from rest_framework import serializers

from search.documents.paper import PaperDocument


class PaperDocumentSerializer(DocumentSerializer):

    class Meta(object):
        document = PaperDocument
        fields = [
            'id',
            'authors',
            'discussion_count',
            'doi',
            'hubs',
            'paper_publish_date',
            'publication_type',
            'score',
            'summary',
            'tagline',
            'title',
            'url',
        ]


class CrossrefPaperSerializer(serializers.Serializer):
    title = serializers.CharField()
    paper_title = serializers.CharField()
    doi = serializers.CharField()
    url = serializers.URLField()
