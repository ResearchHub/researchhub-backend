from django.db import models
from django.db.models import Q
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType

from researchhub_access_group.constants import (
    ACCESS_TYPE_CHOICES,
    ADMIN,
    EDITOR,
    VIEWER,
    MEMBER,
    NO_ACCESS
)
from utils.models import DefaultModel


class PermissionManager(models.Manager):
    def has_user(self, user, **kwargs):
        # Checks if the user exists within the permission
        user_exists = self.filter(
            Q(owner__user=user) |
            Q(owner__permissions__owner__user=user),
            **kwargs
        ).exclude(
            access_type=NO_ACCESS
        ).exists()
        return user_exists

    def has_admin_user(self, user):
        return self.has_user(
            user,
            access_type=ADMIN
        )

    def has_editor_user(self, user):
        return self.has_user(
            user,
            access_type=EDITOR
        )

    def has_member_user(self, user):
        # This might not be a necessary method
        return self.has_user(
            user,
            access_type=MEMBER
        )

    def has_viewer_user(self, user):
        return self.has_user(
            user,
            access_type=VIEWER
        )


class Permission(DefaultModel):
    access_type = models.CharField(
        choices=ACCESS_TYPE_CHOICES,
        default=VIEWER,
        max_length=16
    )
    content_type = models.ForeignKey(
        ContentType,
        related_name='%(class)s_permission',
        on_delete=models.CASCADE,
    )
    object_id = models.PositiveIntegerField()
    owner = models.ForeignKey(
        'user.Organization',
        related_name='user_permissions',
        on_delete=models.CASCADE
    )
    source = GenericForeignKey(
        'content_type',
        'object_id'
    )
    objects = PermissionManager()

    def __str__(self):
        access_type = self.access_type
        owner = self.owner
        return f'Permission Org: {owner.name} - {access_type}'
