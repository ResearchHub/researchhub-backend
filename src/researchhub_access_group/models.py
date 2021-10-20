from django.db import models
from django.db.models import Q
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType

from researchhub_access_group.constants import (
    ACCESS_TYPE_CHOICES,
    ADMIN,
    EDITOR,
    VIEWER,
    MEMBER
)
from user.models import User
from utils.models import DefaultModel


class PermissionManager(models.Manager):
    def has_user(self, user, perm_filters=list(), org_filters=list()):
        # Checks if the user exists within the permission or organization
        main_perm_filter = Q(user=user)
        main_org_filter = Q(organization__permissions__user=user)

        for extra_filter in perm_filters:
            main_perm_filter &= extra_filter

        for extra_filter in org_filters:
            main_org_filter &= extra_filter

        user_exists = self.filter(
            (main_org_filter) |
            (main_perm_filter)
        ).exists()
        return user_exists

    def has_admin_user(self, user):
        return self.has_user(
            user,
            perm_filters=(Q(access_type=ADMIN),),
            org_filters=(Q(organization__permissions__access_type=ADMIN),)
        )

    def has_editor_user(self, user):
        return self.has_user(
            user,
            perm_filters=(Q(access_type=EDITOR),),
            org_filters=(Q(organization__permissions__access_type=MEMBER),)
        )

    def has_viewer_user(self, user):
        return self.has_user(
            user,
            perm_filters=(Q(access_type=VIEWER),),
            org_filters=(
                Q(organization__permissions__access_type=MEMBER) |
                Q(organization__permissions__access_type=ADMIN),
            )
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
    organization = models.ForeignKey(
        'user.Organization',
        null=True,
        on_delete=models.CASCADE,
        related_name='org_permissions',
    )
    source = GenericForeignKey(
        'content_type',
        'object_id'
    )
    user = models.ForeignKey(
        User,
        null=True,
        on_delete=models.CASCADE,
        related_name='permissions',
    )

    objects = PermissionManager()

    def __str__(self):
        user = self.user
        access_type = self.access_type
        if user:
            return f'Permission User: {user.email} - {access_type}'
        else:
            org = self.organization
            return f'Permission Org: {org.name} - {access_type}'
