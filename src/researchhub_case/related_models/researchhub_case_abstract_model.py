from django.db import models

from researchhub_case.constants.case_constants import RH_CASE_TYPES
from user.models import User
from utils.models import DefaultModel


class AbstractResearchhubCase(DefaultModel):
    case_type = models.CharField(
      blank=False,
      choices=RH_CASE_TYPES,
      max_length=32,
      null=False,
    )
    creator = models.ForeignKey(
        User,
        blank=False,
        default=0,
        null=False,
        on_delete=models.CASCADE,
        related_name='created_case',
    )
    moderator = models.ForeignKey(
        User,
        blank=True,
        null=True,
        on_delete=models.CASCADE,
        related_name='moderating_case',
    )
    requestor = models.ForeignKey(
        User,
        blank=False,
        default=0,
        null=False,
        on_delete=models.CASCADE,
        related_name='requested_case',
    )

    class Meta:
        abstract = True
