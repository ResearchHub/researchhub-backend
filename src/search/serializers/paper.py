from django_elasticsearch_dsl_drf.serializers import DocumentSerializer
from rest_framework import serializers

from search.documents.paper import PaperDocument
from paper.models import Paper


class PaperDocumentSerializer(DocumentSerializer):
    slug = serializers.SerializerMethodField()
    abstract = serializers.SerializerMethodField()
    highlight = serializers.SerializerMethodField()

    class Meta(object):
        document = PaperDocument
        fields = [
            'id',
            'authors',
            'raw_authors',
            'authors_str',
            'hot_score',
            'discussion_count',
            'doi',
            'hubs',
            'paper_publish_date',
            'publication_type',
            'score',
            'summary',
            'title',
            'abstract',
            'paper_title',
            'url',
        ]

    def get_highlight(self, obj):
        if hasattr(obj.meta, 'highlight'):
            return obj.meta.highlight.__dict__['_d_']
        return {}

    def get_slug(self, hit):
        slug = ''
        try:
            paper_id = hit['id']
            paper = Paper.objects.get(id=paper_id)
            slug = paper.slug
        except:
            pass

        return slug

    def get_abstract(self, hit):
        abstract = ''
        try:
            paper_id = hit['id']
            paper = Paper.objects.get(id=paper_id)
            abstract = paper.abstract
        except:
            pass

        return abstract


class CrossrefPaperSerializer(serializers.Serializer):
    # TODO: Add description
    id = serializers.IntegerField()
    meta = serializers.JSONField()
    title = serializers.CharField()
    paper_title = serializers.CharField()
    doi = serializers.CharField()
    url = serializers.URLField()
