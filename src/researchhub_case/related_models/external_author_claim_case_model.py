from django.db import models

from researchhub_case.constants.case_constants import (
    AUTHOR_CLAIM_CASE_STATUS,
    INITIATED,
)
from researchhub_case.related_models.researchhub_case_abstract_model import (
    AbstractResearchhubCase,
)


class ExternalAuthorClaimCase(AbstractResearchhubCase):
    h_index = models.IntegerField(default=0)
    publication_count = models.IntegerField(default=0)
    semantic_scholar_id = models.CharField(max_length=16)
    status = models.CharField(
        choices=AUTHOR_CLAIM_CASE_STATUS,
        default=INITIATED,
        max_length=32,
        null=False,
    )
