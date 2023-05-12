from django.contrib.contenttypes.fields import GenericRelation
from django.db import models

from researchhub_access_group.constants import ADMIN, MEMBER, VIEWER
from researchhub_access_group.models import Permission
from user.constants.organization_constants import ORG_TYPE_CHOICES, ORGANIZATION
from utils.models import DefaultModel


class Organization(DefaultModel):
    cover_image = models.FileField(
        max_length=1024,
        upload_to="organizations/cover_image/%Y/%m/%d",
        default=None,
        null=True,
        blank=True,
    )
    description = models.CharField(default="", max_length=256)
    name = models.CharField(max_length=128)
    note_created = models.BooleanField(default=False)
    org_type = models.CharField(
        choices=ORG_TYPE_CHOICES, default=ORGANIZATION, max_length=16
    )
    permissions = GenericRelation(
        Permission,
        related_name="organization",
        related_query_name="org_source",
    )
    slug = models.SlugField(default="", max_length=1024, unique=True)
    user = models.OneToOneField(
        "user.User",
        null=True,
        related_name="organization",
        on_delete=models.CASCADE,
    )

    def __str__(self):
        return f"Id: {self.id} Name: {self.name}"

    def org_content_has_user(self, user, **filters):
        # Since organizations only contains notes for now,
        # check if notes have user permission
        notes = self.created_notes.filter(unified_document__permissions__user=user)
        return notes.exists()

    def org_has_user(self, user, content_user=True, **filters):
        permissions = self.permissions
        org_permission = permissions.filter(user=user, **filters).exists()
        if content_user:
            has_perm = org_permission or self.org_content_has_user(user, **filters)
        else:
            has_perm = org_permission
        return has_perm

    def org_has_admin_user(self, user, content_user=True):
        return self.org_has_user(user, content_user=content_user, access_type=ADMIN)

    def org_has_member_user(self, user, content_user=True):
        return self.org_has_user(user, content_user=content_user, access_type=MEMBER)

    def org_has_viewer_user(self, user, content_user=True):
        return self.org_has_user(user, content_user=content_user, access_type=VIEWER)
