from django.db import models

from researchhub_case.constants.case_constants import (
    AUTHOR_CLAIM_CASE_STATUS, INITIATED
)
from researchhub_case.related_models.researchhub_case_abstract_model import (
  AbstractResearchhubCase
)
from user.models import Author


class AuthorClaimCase(AbstractResearchhubCase):
    status = models.CharField(
      choices=AUTHOR_CLAIM_CASE_STATUS,
      default=INITIATED,
      max_length=32,
      null=False,
    )
    target_author = models.ForeignKey(
      Author,
      blank=False,
      default=0,
      null=False,
      on_delete=models.CASCADE,
      related_name='claim_case',
    )
    validation_attempt_count = models.IntegerField(
      blank=False,
      default=-1,
      help_text="Number of attempts to validate themselves given token",
      null=False
    )
    validation_token = models.CharField(
      blank=True,
      default=None,
      help_text="Used to authenticate User's identity. See post_save signal",
      max_length=255,
      null=True,
    )
