from rest_framework.serializers import ModelSerializer, SerializerMethodField

from .researchhub_case_abstract_serializer import EXPOSABLE_FIELDS
from researchhub_case.models import AuthorClaimCase
from user.models import Author, User
from user.serializers import AuthorSerializer, UserSerializer
from paper.models import Paper


class AuthorClaimCaseSerializer(ModelSerializer):
    moderator = SerializerMethodField(method_name='get_moderator')
    requestor = SerializerMethodField()
    target_author = SerializerMethodField(method_name='get_target_author')

    def create(self, validated_data):
        request_data = self.context.get('request').data
        moderator_id = request_data.get('moderator')
        requestor_id = request_data.get('requestor')
        target_author_id = request_data.get('target_author')
        moderator = User.objects.filter(id=moderator_id).first()
        requestor = User.objects.filter(id=requestor_id).first()
        author = request_data.get('author')

        if not target_author_id:
            first_name = author.get('first_name')
            last_name = author.get('last_name')
            target_author = Author.objects.filter(
                first_name=first_name,
                last_name=last_name,
                claimed=False
            )

            if target_author.exists():
                target_author = target_author.first()
            else:
                target_author = Author.objects.create(
                    first_name=first_name,
                    last_name=last_name,
                    claimed=False,
                )

                author_papers = Paper.objects.filter(
                    raw_authors__contains=[
                        {
                            "first_name": first_name,
                            "last_name": last_name
                        }
                    ]
                )

                for paper in author_papers:
                    paper.authors.add(target_author)
        else:
            target_author = Author.objects.filter(id=target_author_id).first()

        return AuthorClaimCase.objects.create(
            **validated_data,
            moderator=moderator,
            requestor=requestor,
            target_author=target_author
        )

    def get_moderator(self, case):
        serializer = UserSerializer(case.moderator)
        if (serializer is not None):
            return serializer.data
        return None

    def get_requestor(self, case):
        serializer = UserSerializer(case.requestor)
        if (serializer is not None):
            return serializer.data
        return None

    def get_target_author(self, case):
        serializer = AuthorSerializer(case.target_author)
        if (serializer is not None):
            return serializer.data
        return None

    class Meta(object):
        model = AuthorClaimCase
        fields = [
          *EXPOSABLE_FIELDS,
          'provided_email',
          'status',
          'target_author',
          'token_generated_time',
          'validation_attempt_count',
          'validation_token',
        ]
        read_only_fields = [
          'status',
          'token_generated_time',
          'validation_attempt_count',
          'validation_token',
        ]
