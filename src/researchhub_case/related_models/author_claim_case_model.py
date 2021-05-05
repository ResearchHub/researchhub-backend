from django.db import models

from researchhub_case.constants.case_constants import AUTHOR_CLAIM_CASE_STATUS
from researchhub_case.related_models.researchhub_case_abstract_model import (
  AbstractResearchhubCase
)


class AuthorClaimCase(AbstractResearchhubCase):
    status = models.CharField(
      choices=AUTHOR_CLAIM_CASE_STATUS,
      default='OPEN',
      max_length=32,
      null=False,
    )
