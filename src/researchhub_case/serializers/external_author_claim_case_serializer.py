from rest_framework.serializers import ModelSerializer

from researchhub_case.models import ExternalAuthorClaimCase

from .researchhub_case_abstract_serializer import EXPOSABLE_FIELDS


class ExternalAuthorClaimCaseSerializer(ModelSerializer):
    class Meta(object):
        model = ExternalAuthorClaimCase
        fields = [
            *EXPOSABLE_FIELDS,
            "h_index",
            "publication_count",
            "status",
            "semantic_scholar_id",
        ]
        read_only_fields = [
            # "case_type",
            # "creator",
            "moderator",
            # "requestor",
            "status",
        ]
