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
    creator = models.OneToOneField(
        User,
        blank=False,
        null=False,
        on_delete=models.PROTECT,
        related_name='case_creator',
    )
    moderator = models.OneToOneField(
        User,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name='case_moderator',
    )
    requestor = models.OneToOneField(
        User,
        blank=False,
        null=False,
        on_delete=models.PROTECT,
        related_name='case_requestor',
    )

    class Meta:
        abstract = True
