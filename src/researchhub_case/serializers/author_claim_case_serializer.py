from rest_framework.serializers import ModelSerializer

from researchhub_case.models import AuthorClaimCase


class AuthorClaimCaseSerializer(ModelSerializer):

    class Meta(object):
        model = AuthorClaimCase
        fields = [
          'case_type',
          'creator',
          'id',
          'moderator',
          'requestor',
        ]
