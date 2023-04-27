from django_elasticsearch_dsl_drf.serializers import DocumentSerializer
from rest_framework import serializers

from search.documents import UserDocument
from user.models import Author, User
from user.serializers import AuthorSerializer, UserSerializer


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
