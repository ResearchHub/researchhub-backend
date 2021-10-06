from django.db import models

from researchhub_access_group.models import ResearchhubAccessGroup
from researchhub_access_group.constants import ADMIN, EDITOR, VIEWER
from utils.models import DefaultModel


class Organization(DefaultModel):
    access_group = models.ForeignKey(
        ResearchhubAccessGroup,
        related_name='organizations',
        on_delete=models.CASCADE,
    )
    cover_image = models.FileField(
        max_length=512,
        upload_to='organizations/cover_image/%Y/%m/%d',
        default=None,
        null=True,
        blank=True
    )
    description = models.CharField(default='', max_length=256)
    name = models.CharField(max_length=64, unique=True)
    slug = models.SlugField(default='', max_length=1024, unique=True)

    def has_user(self, user, **filters):
        access_group = self.access_group
        return access_group.permissions.filter(
            user=user,
            **filters
        ).exists()

    def org_has_admin_user(self, user):
        return self.has_user(user, access_type=ADMIN)

    def org_has_editor_user(self, user):
        return self.has_user(user, access_type=EDITOR)

    def org_has_viewer_user(self, user):
        return self.has_user(user, access_type=VIEWER)
