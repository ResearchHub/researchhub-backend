from rest_framework.serializers import ModelSerializer

from researchhub_case.models import AuthorClaimCase
from .researchhub_case_abstract_serializer import EXPOSABLE_FIELDS


class AuthorClaimCaseSerializer(ModelSerializer):

    class Meta(object):
        model = AuthorClaimCase
        fields = [
          *EXPOSABLE_FIELDS,
          'target_author',
          'status',
        ]
