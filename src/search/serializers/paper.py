from django_elasticsearch_dsl_drf.serializers import DocumentSerializer
from rest_framework import serializers

from search.documents.paper import PaperDocument
from paper.models import Paper


class PaperDocumentSerializer(DocumentSerializer):
    slug = serializers.SerializerMethodField()
    abstract = serializers.SerializerMethodField()

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

    def get_slug(self, hit):
        # TODO: Better way to add slug from a search hit?
        paper_id = hit['id']
        paper = Paper.objects.get(id=paper_id)
        slug = paper.slug
        return slug

    def get_abstract(self, hit):
        paper_id = hit['id']
        paper = Paper.objects.get(id=paper_id)
        abstract = paper.abstract
        return abstract


class CrossrefPaperSerializer(serializers.Serializer):
    # TODO: Add description
    id = serializers.IntegerField()
    meta = serializers.JSONField()
    title = serializers.CharField()
    paper_title = serializers.CharField()
    doi = serializers.CharField()
    url = serializers.URLField()
