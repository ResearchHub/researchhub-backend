from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import Q

from researchhub_access_group.constants import (
    ACCESS_TYPE_CHOICES,
    ADMIN,
    EDITOR,
    MEMBER,
    NO_ACCESS,
    VIEWER,
)
from utils.models import DefaultModel


class PermissionManager(models.Manager):
    def has_user(self, user, perm_filters=None, org_filters=None):
        if perm_filters is None:
            perm_filters = []
        if org_filters is None:
            org_filters = []

        # Checks if the user exists within the permission or organization
        main_perm_filter = Q(user=user) & ~Q(access_type=NO_ACCESS)
        main_org_filter = Q(organization__permissions__user=user) & ~Q(
            access_type=NO_ACCESS
        )

        if perm_filters is not None:
            for extra_filter in perm_filters:
                main_perm_filter &= extra_filter
        else:
            main_perm_filter = Q()

        if org_filters is not None:
            for extra_filter in org_filters:
                main_org_filter &= extra_filter
        else:
            main_org_filter = Q()

        user_exists = self.filter((main_org_filter) | (main_perm_filter)).exists()
        return user_exists

    def has_admin_user(self, user, perm=True, org=True):
        perm_filters = None
        org_filters = None

        if perm:
            perm_filters = (Q(access_type=ADMIN),)
        if org:
            org_filters = (Q(organization__permissions__access_type=ADMIN),)
        return self.has_user(user, perm_filters=perm_filters, org_filters=org_filters)

    def has_editor_user(self, user, perm=True, org=True):
        perm_filters = None
        org_filters = None

        if perm:
            perm_filters = (Q(access_type=EDITOR),)
        if org:
            org_filters = (Q(organization__permissions__access_type=MEMBER),)
        return self.has_user(user, perm_filters=perm_filters, org_filters=org_filters)

    def has_viewer_user(self, user, perm=True, org=True):
        perm_filters = None
        org_filters = None

        if perm:
            perm_filters = (Q(access_type=VIEWER),)
        if org:
            org_filters = (
                Q(organization__permissions__access_type=MEMBER)
                | Q(organization__permissions__access_type=ADMIN),
            )
        return self.has_user(user, perm_filters=perm_filters, org_filters=org_filters)


class Permission(DefaultModel):
    access_type = models.CharField(
        choices=ACCESS_TYPE_CHOICES, default=VIEWER, max_length=16
    )
    content_type = models.ForeignKey(
        ContentType,
        related_name="%(class)s_permission",
        on_delete=models.CASCADE,
    )
    object_id = models.PositiveIntegerField()
    organization = models.ForeignKey(
        "user.Organization",
        null=True,
        on_delete=models.CASCADE,
        related_name="org_permissions",
    )
    source = GenericForeignKey("content_type", "object_id")
    user = models.ForeignKey(
        "user.User",
        null=True,
        on_delete=models.CASCADE,
        related_name="permissions",
        help_text="single user that belongs to this permission",
    )

    objects = PermissionManager()

    def __str__(self):
        user = self.user
        org = self.organization
        access_type = self.access_type
        if user and not org:
            return f"Permission User: {user.email} - {access_type}"
        else:
            return f"Permission Org: {org.name} - {access_type}"
