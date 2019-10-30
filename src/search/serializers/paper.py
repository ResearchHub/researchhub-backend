from django_elasticsearch_dsl_drf.serializers import DocumentSerializer

from search.documents.paper import PaperDocument


class PaperDocumentSerializer(DocumentSerializer):

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
        ]
