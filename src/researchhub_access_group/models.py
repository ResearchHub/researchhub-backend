from django.db import models

from researchhub.settings import BASE_FRONTEND_URL
from researchhub_access_group.constants import (
    ACCESS_TYPE_CHOICES,
    ADMIN,
    EDITOR,
    VIEWER
)
from user.models import User
from utils.models import DefaultModel


class AccessGroupManager(models.Manager):
    def has_user(self, user, **filters):
        return self.filter(
            permissions__user=user,
            **filters
        ).exists()

    def has_admin_user(self, user):
        return self.has_user(user, permissions__access_type=ADMIN)

    def has_editor_user(self, user):
        return self.has_user(user, permissions__access_type=EDITOR)

    def has_viewer_user(self, user):
        return self.has_user(user, permissions__access_type=VIEWER)


class ResearchhubAccessGroup(DefaultModel):
    key = models.CharField(max_length=32)
    name = models.CharField(max_length=32)

    @property
    def sharable_link(self):
        # TODO: UPDATE URL
        return f'{BASE_FRONTEND_URL}/placeholder/{self.key}'

    def has_user(self, user, **filters):
        return self.permissions.filter(
            user=user,
            **filters
        ).exists()

    def has_admin_user(self, user):
        return self.has_user(user, access_type=ADMIN)

    def has_editor_user(self, user):
        return self.has_user(user, access_type=EDITOR)

    def has_viewer_user(self, user):
        return self.has_user(user, access_type=VIEWER)

    objects = AccessGroupManager()


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
