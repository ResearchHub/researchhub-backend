from django_elasticsearch_dsl_drf.serializers import DocumentSerializer
from rest_framework import serializers

from search.documents.paper import PaperDocument
from paper.models import Paper
from utils.sentry import log_error


class PaperDocumentSerializer(DocumentSerializer):
    slug = serializers.SerializerMethodField()
    highlight = serializers.SerializerMethodField()
    unified_doc_id = serializers.SerializerMethodField()

    class Meta(object):
        document = PaperDocument
        fields = [
            'id',
            'authors',
            'abstract',
            'uploaded_date',
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
            'uploaded_by',
            'unified_doc_id',
            'url',
        ]

    def get_highlight(self, obj):
        if hasattr(obj.meta, 'highlight'):
            return obj.meta.highlight.__dict__['_d_']
        return {}

    def get_slug(self, hit):
        slug = ''
        try:
            obj = Paper.objects.get(id=hit['id'])
            slug = obj.slug
        except:
            pass

        return slug

    def get_unified_doc_id(self, paper):
        try:
            obj = Paper.objects.get(id=paper.id)
            return obj.unified_document.id
        except Exception as e:
            log_error(e, 'A Paper must have unified document')


class CrossrefPaperSerializer(serializers.Serializer):
    # TODO: Add description
    id = serializers.IntegerField()
    meta = serializers.JSONField()
    title = serializers.CharField()
    paper_title = serializers.CharField()
    doi = serializers.CharField()
    url = serializers.URLField()
