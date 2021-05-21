from rest_framework.serializers import ModelSerializer, SerializerMethodField

from .researchhub_case_abstract_serializer import EXPOSABLE_FIELDS
from researchhub_case.models import AuthorClaimCase
from user.serializers import AuthorSerializer, UserSerializer


class AuthorClaimCaseSerializer(ModelSerializer):
    moderator = SerializerMethodField()
    requestor = SerializerMethodField()
    target_author = SerializerMethodField()

    def get_moderator(self, case):
        return UserSerializer(case.moderator).data

    def get_requestor(self, case):
        return UserSerializer(case.requestor).data

    def get_target_author(self, case):
        return AuthorSerializer(case.target_author).data

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
