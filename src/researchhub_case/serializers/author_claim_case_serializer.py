from rest_framework.serializers import ModelSerializer

from researchhub_case.models import AuthorClaimCase
from .researchhub_case_abstract_serializer import EXPOSABLE_FIELDS


class AuthorClaimCaseSerializer(ModelSerializer):

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
