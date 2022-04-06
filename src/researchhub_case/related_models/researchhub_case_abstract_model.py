from django.db import models

from researchhub_case.constants.case_constants import RH_CASE_TYPES
from utils.models import DefaultModel


class AbstractResearchhubCase(DefaultModel):
    case_type = models.CharField(
      blank=False,
      choices=RH_CASE_TYPES,
      max_length=32,
      null=False,
    )
    creator = models.ForeignKey(
        'user.User',
        blank=False,
        null=True,
        on_delete=models.CASCADE,
        related_name='created_cases',
    )
    moderator = models.ForeignKey(
        'user.User',
        blank=True,
        null=True,
        on_delete=models.CASCADE,
        related_name='moderating_cases',
    )
    requestor = models.ForeignKey(
        'user.User',
        blank=False,
        null=True,
        on_delete=models.CASCADE,
        related_name='requested_cases',
    )

    class Meta:
        abstract = True
