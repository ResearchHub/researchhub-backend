from django.db import models
from django.contrib.contenttypes.fields import GenericRelation

from researchhub_access_group.models import Permission
from researchhub_access_group.constants import ADMIN, MEMBER, VIEWER
from user.models import User
from utils.models import DefaultModel


class Organization(DefaultModel):
    cover_image = models.FileField(
        max_length=512,
        upload_to='organizations/cover_image/%Y/%m/%d',
        default=None,
        null=True,
        blank=True
    )
    note_created = models.BooleanField(default=False, null=True, blank=True)
    description = models.CharField(default='', max_length=256)
    name = models.CharField(max_length=64, unique=True)
    permissions = GenericRelation(
        Permission,
        related_name='organization'
    )
    slug = models.SlugField(default='', max_length=1024, unique=True)
    user = models.OneToOneField(
        User,
        null=True,
        related_name='organization',
        on_delete=models.CASCADE,
    )

    def org_has_user(self, user, **filters):
        permissions = self.permissions
        return permissions.filter(
            owner__user=user,
            **filters
        ).exists()

    def org_has_admin_user(self, user):
        return self.org_has_user(user, access_type=ADMIN)

    def org_has_member_user(self, user):
        return self.org_has_user(user, access_type=MEMBER)

    def org_has_viewer_user(self, user):
        return self.org_has_user(user, access_type=VIEWER)
