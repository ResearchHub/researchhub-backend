from rest_framework.serializers import ModelSerializer

from researchhub_case.models import ExternalAuthorClaimCase

from .abstract_researchhub_case_serializer import DynamicAbstractResearchhubCase
from .researchhub_case_abstract_serializer import EXPOSABLE_FIELDS


class ExternalAuthorClaimCaseSerializer(ModelSerializer):
    class Meta:
        model = ExternalAuthorClaimCase
        fields = [
            *EXPOSABLE_FIELDS,
            "google_scholar_id",
            "h_index",
            "publication_count",
            "status",
            "semantic_scholar_id",
        ]
        read_only_fields = [
            "created_date",
            "id",
            "moderator",
            "status",
            "updated_date,",
        ]


class DynamicExternalAuthorClaimCaseSerializer(DynamicAbstractResearchhubCase):
    class Meta:
        model = ExternalAuthorClaimCase
        fields = "__all__"
