from django_elasticsearch_dsl_drf.serializers import DocumentSerializer

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
