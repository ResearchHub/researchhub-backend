from django.db.models import Q
from rest_framework.serializers import (
    CurrentUserDefault,
    HiddenField,
    ModelSerializer,
    SerializerMethodField,
)

from citation.models import CitationProject
from researchhub_access_group.constants import ADMIN, EDITOR
from user.related_models.user_model import User
from user.serializers import MinimalUserSerializer


class CitationProjectSerializer(ModelSerializer):
    # HiddenField doesn't update instance if the field is not empty
    created_by = HiddenField(default=CurrentUserDefault())
    updated_by = HiddenField(default=CurrentUserDefault())
    children = SerializerMethodField()
    admins = SerializerMethodField(read_only=True)
    editors = SerializerMethodField(read_only=True)
    current_user_has_access = SerializerMethodField(read_only=True)

    class Meta:
        model = CitationProject
        fields = "__all__"

    """ ----- Django Method Overrides -----"""

    """ ----- Serializer Methods -----"""

    def get_admins(self, project):
        admin_ids = project.permissions.filter(access_type=ADMIN).values_list("user")
        return MinimalUserSerializer(
            User.objects.filter(id__in=admin_ids), many=True
        ).data

    def get_editors(self, project):
        editor_ids = project.permissions.filter(access_type=EDITOR).values_list("user")
        return MinimalUserSerializer(
            User.objects.filter(id__in=editor_ids), many=True
        ).data

    def get_current_user_has_access(self, project):
        current_user = self.context.get("request").user
        return project.get_current_user_has_access(current_user)

    def get_children(self, project):
        return CitationProjectSerializer(
            context=self.context,
            instance=project.children.filter(
                Q(is_public=True)
                | Q(
                    is_public=False,
                    permissions__user=self.context.get("request").user,
                )
            ).distinct(),
            many=True,
        ).data

    """ ----- Private Methods -----"""
