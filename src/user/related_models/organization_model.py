from django.db import models

from researchhub_access_group.models import Permission
from researchhub_access_group.constants import ADMIN, EDITOR, VIEWER
from utils.models import DefaultModel


class Organization(DefaultModel):
    permissions = models.ManyToManyField(
        Permission,
        related_name='direct_organization',
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

    def org_has_user(self, user, **filters):
        permissions = self.permissions
        return permissions.filter(
            user=user,
            **filters
        ).exists()

    def org_has_admin_user(self, user):
        return self.org_has_user(user, access_type=ADMIN)

    def org_has_editor_user(self, user):
        return self.org_has_user(user, access_type=EDITOR)

    def org_has_viewer_user(self, user):
        return self.org_has_user(user, access_type=VIEWER)
