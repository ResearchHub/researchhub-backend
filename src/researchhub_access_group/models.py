from django.db import models

from user.models import User
from utils.models import DefaultModel


class ResearchhubAccessGroup(DefaultModel):
    # Groups
    admins = models.ManyToManyField(
        User,
        related_name="access_admin_groups"
    )
    editors = models.ManyToManyField(
        User,
        related_name="access_editor_groups"
    )
    viewers = models.ManyToManyField(
        User,
        related_name="access_viewing_groups"
    )

    is_public = models.BooleanField(
      blank=False,
      default=True,
      help_text="Public means it's accessible disregarding user's status",
      null=False,
    )
