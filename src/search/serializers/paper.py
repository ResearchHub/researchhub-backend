from django_elasticsearch_dsl_drf.serializers import DocumentSerializer
from rest_framework import serializers

from search.documents.paper import PaperDocument


class PaperDocumentSerializer(DocumentSerializer):
    slug = serializers.SerializerMethodField()

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
            'title',
            'url',
        ]

    def get_slug(self, paper):
        slug = paper.get_slug()
        return slug


class CrossrefPaperSerializer(serializers.Serializer):
    # TODO: Add description
    id = serializers.IntegerField()
    meta = serializers.JSONField()
    title = serializers.CharField()
    paper_title = serializers.CharField()
    doi = serializers.CharField()
    url = serializers.URLField()
