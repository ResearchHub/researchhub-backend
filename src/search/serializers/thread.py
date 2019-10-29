from django_elasticsearch_dsl_drf.serializers import DocumentSerializer

from search.documents.thread import ThreadDocument


class ThreadDocumentSerializer(DocumentSerializer):

    class Meta(object):
        # Specify the correspondent document class
        document = ThreadDocument

        # List the serializer fields. Note, that the order of the fields
        # is preserved in the ViewSet.
        fields = (
            'title',
            'id',
            'paper'
        )
