from django_elasticsearch_dsl_drf.serializers import DocumentSerializer

from search.documents import UserDocument


class UserDocumentSerializer(DocumentSerializer):
    class Meta:
        document = UserDocument
        fields = (
            "id",
            "full_name",
            "first_name",
            "last_name",
            "reputation",
            "author_profile",
        )
