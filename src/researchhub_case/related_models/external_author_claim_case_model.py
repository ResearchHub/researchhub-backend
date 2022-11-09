from django.db import models

from researchhub_case.constants.case_constants import (
    APPROVED,
    AUTHOR_CLAIM_CASE_STATUS,
    INITIATED,
)
from researchhub_case.related_models.researchhub_case_abstract_model import (
    AbstractResearchhubCase,
)
from researchhub_case.tasks import celery_add_author_citations


class ExternalAuthorClaimCase(AbstractResearchhubCase):
    h_index = models.IntegerField(default=0, null=True)
    publication_count = models.IntegerField(default=0, null=True)
    semantic_scholar_id = models.CharField(max_length=16, null=True)
    google_scholar_id = models.CharField(max_length=16, null=True)
    status = models.CharField(
        choices=AUTHOR_CLAIM_CASE_STATUS,
        default=INITIATED,
        max_length=32,
        null=False,
    )

    def approve_google_scholar(self):
        celery_add_author_citations.apply_async(
            (self.requestor.id, self.google_scholar_id), priority=5, countdown=10
        )
        self.status = APPROVED
        self.save()
