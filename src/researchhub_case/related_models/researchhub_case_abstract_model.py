from django.db import models

from utils.models import DefaultModel
from user.models import User


class AbstractResearchhubCase(DefaultModel):
    creator = models.OneToOneField(
        User,
        blank=False,
        null=False,
        on_delete=models.SET_NULL,
        related_name='case_creator',
    )
    moderator = models.OneToOneField(
        User,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name='case_moderator',
    )

