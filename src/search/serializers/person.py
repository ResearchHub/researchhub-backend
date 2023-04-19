from django_elasticsearch_dsl_drf.serializers import DocumentSerializer
from rest_framework import serializers

from search.documents import PersonDocument
from user.models import Author, User
from user.serializers import AuthorSerializer, UserSerializer


class PersonDocumentSerializer(DocumentSerializer):
    profile_image = serializers.SerializerMethodField()
    headline = serializers.SerializerMethodField()
    user_reputation = serializers.SerializerMethodField()
    person_types = serializers.SerializerMethodField()
    author_profile = serializers.SerializerMethodField()
    user = serializers.SerializerMethodField()

    class Meta(object):
        document = PersonDocument
        fields = [
            "id",
            "first_name",
            "last_name",
            "full_name",
            "profile_image",
            "headline",
            "description",
            "author_score",
            "user_reputation",
            "person_types",
            "user",
            "name_suggest",
            "author_profile",
        ]
        read_only_fields = fields

    def get_user(self, document):
        try:
            if "user" in document.person_types:
                user = Author.objects.get(id=document.id).user
                return UserSerializer(user).data
        except:
            # The object no longer exist in the DB
            pass

    def get_author_profile(self, document):
        try:
            author = Author.objects.get(id=document.id)
            return AuthorSerializer(
                author,
                read_only=True,
            ).data
        except:
            # The object no longer exist in the DB
            pass

    def get_person_types(self, document):
        return list(document.person_types)

    def get_user_reputation(self, document):
        return document.user_reputation

    def get_profile_image(self, document):
        if document.profile_image is not None:
            return document.profile_image

    def get_headline(self, document):
        if document.headline is not None:
            return document.headline.to_dict()
