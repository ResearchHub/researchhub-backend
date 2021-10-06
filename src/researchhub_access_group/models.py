from django.db import models

from researchhub.settings import BASE_FRONTEND_URL
from researchhub_access_group.constants import ACCESS_TYPE_CHOICES, VIEWER
from user.models import User
from utils.models import DefaultModel


class ResearchhubAccessGroup(DefaultModel):
    key = models.CharField(max_length=32)
    name = models.CharField(max_length=32)

    @property
    def sharable_link(self):
        # TODO: UPDATE URL
        return f'{BASE_FRONTEND_URL}/placeholder/{self.key}'


class Permission(DefaultModel):
    access_group = models.ForeignKey(
        ResearchhubAccessGroup,
        related_name='permissions',
        on_delete=models.CASCADE,
    )
    access_type = models.CharField(
        choices=ACCESS_TYPE_CHOICES,
        default=VIEWER,
        max_length=8
    )
    user = models.ForeignKey(
        User,
        related_name='permissions',
        on_delete=models.CASCADE
    )
