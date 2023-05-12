from django.db import models
from django.contrib.contenttypes.fields import GenericRelation
from researchhub_access_group.constants import ADMIN, EDITOR
from researchhub_access_group.related_models.permission_model import Permission

from user.models import Organization
from utils.models import DefaultAuthenticatedModel


class CitationProject(DefaultAuthenticatedModel):

    """--- MODEL FIELDS ---"""

    is_public = models.BooleanField(
        blank=True,
        default=True,
        null=False,
    )
    parent = models.ForeignKey(
        "self",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="children",
    )
    permissions = GenericRelation(
        Permission,
        related_name="citation_projects",
        related_query_name="citation_project",
    )
    project_name = models.CharField(
        max_length=1024,
    )
    organization = models.ForeignKey(
        Organization,
        related_name="citation_projects",
        on_delete=models.CASCADE,
    )

    """--- METHODS ---"""

    def add_editors(self, editor_ids=[]):
        print("################")
        print("editor_ids: ", editor_ids)
        try:
            for editor_id in editor_ids:
                editor_exists = self.permissions.filter(
                    access_type=EDITOR, user=editor_id
                ).exists()
                if not editor_exists:
                    self.permissions.create(access_type=EDITOR, user=editor_id)
            return True
        except Exception as error:
            return False

    def remove_editors(self, editor_ids):
        try:
            for editor_id in editor_ids:
                self.permissions.create(access_type=EDITOR, user=editor_id)
            return True
        except Exception as error:
            return False

    def get_current_user_has_access(self, user):
        org_has_user = self.organization.org_has_user(user)
        if not org_has_user:
            return False

        if self.is_public:
            return True
        else:
            return self.permissions.filter(user=user).exists()

    def set_creator_as_admin(self):
        try:
            self.permissions.create(access_type=ADMIN, user=self.created_by)
            return True
        except Exception as error:
            return False
