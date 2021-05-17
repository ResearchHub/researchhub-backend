from django.db import models

from researchhub_case.constants.case_constants import (
    AUTHOR_CLAIM_CASE_STATUS, INITIATED
)
from researchhub_case.related_models.researchhub_case_abstract_model import (
  AbstractResearchhubCase
)
from user.models import Author


class AuthorClaimCase(AbstractResearchhubCase):
    provided_email = models.EmailField(
      blank=False,
      help_text=(
        'Requestors may use this field to validate themselves with this email'
      ),
      null=False,
    )
    status = models.CharField(
      choices=AUTHOR_CLAIM_CASE_STATUS,
      default=INITIATED,
      max_length=32,
      null=False,
    )
    target_author = models.ForeignKey(
      Author,
      blank=False,
      default=-1,
      null=False,
      on_delete=models.CASCADE,
      related_name='related_claim_cases',
    )
    token_generated_time = models.IntegerField(
      blank=True,
      default=None,
      help_text="Intentionally setting as a int field",
      null=True,
    )
    validation_attempt_count = models.IntegerField(
      blank=False,
      default=-1,
      help_text="Number of attempts to validate themselves given token",
      null=False
    )
    validation_token = models.CharField(
      blank=True,
      db_index=True,
      default=None,
      help_text="See author_claim_case_post_create_signal",
      max_length=255,
      null=True,
      unique=True,
    )
