import logging

from opensearchpy.helpers.utils import AttrList
from rest_framework import serializers

from user.models import Author, User
from user.serializers import AuthorSerializer, UserSerializer

logger = logging.getLogger(__name__)


class PersonDocumentSerializer(serializers.ModelSerializer):
    profile_image = serializers.SerializerMethodField()
    user_reputation = serializers.SerializerMethodField()
    person_types = serializers.SerializerMethodField()
    author_profile = serializers.SerializerMethodField()
    user = serializers.SerializerMethodField()
    institutions = serializers.SerializerMethodField()

    class Meta(object):
        model = Author
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
            "author_profile",
            "institutions",
        ]
        read_only_fields = fields

    def get_user(self, document):
        try:
            if "user" in document.person_types:
                user = Author.objects.get(id=document.id).user
                return UserSerializer(user).data
        except (Author.DoesNotExist, User.DoesNotExist):
            logger.warning("Missing author or user for author id %s", document.id)
            return None
        except Exception:
            logger.exception("Error retrieving user for author id %s", document.id)
            return None

    def get_author_profile(self, document):
        try:
            author = Author.objects.get(id=document.id)
            return AuthorSerializer(
                author,
                read_only=True,
            ).data
        except Author.DoesNotExist:
            logger.warning("Author with id %s does not exist.", document.id)
            return None
        except Exception:
            logger.exception(
                "Error retrieving author profile for author id %s", document.id
            )
            return None

    def get_person_types(self, document):
        return list(document.person_types)

    def get_user_reputation(self, document):
        return document.user_reputation

    def get_institutions(self, document):
        institutions_data = document.institutions
        if isinstance(institutions_data, AttrList):
            return [
                {"id": institution["id"], "name": institution["name"]}
                for institution in institutions_data
            ]

    def get_profile_image(self, document):
        if document.profile_image is not None:
            return document.profile_image
