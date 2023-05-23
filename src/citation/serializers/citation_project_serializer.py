from django.db.models import Q
from rest_framework.serializers import (
    SerializerMethodField,
)

from citation.models import CitationProject
from researchhub_access_group.constants import EDITOR
from user.related_models.user_model import User
from user.serializers import MinimalUserSerializer
from utils.serializers import DefaultAuthenticatedSerializer


class CitationProjectSerializer(DefaultAuthenticatedSerializer):
    children = SerializerMethodField()
    current_user_is_admin = SerializerMethodField(read_only=True)
    editors = SerializerMethodField(read_only=True)

    class Meta:
        model = CitationProject
        fields = "__all__"

    """ ----- Django Method Overrides -----"""

    """ ----- Serializer Methods -----"""

    def get_current_user_is_admin(self, project_instance):
        current_user = self.context.get("request").user
        return project_instance.get_is_user_admin(current_user)

    def get_editors(self, project):
        editor_ids = project.permissions.filter(access_type=EDITOR).values_list("user")
        return MinimalUserSerializer(
            User.objects.filter(id__in=editor_ids), many=True
        ).data

    def get_current_user_has_access(self, project_instance):
        current_user = self.context.get("request").user
        return project_instance.get_user_has_access(current_user)

    def get_children(self, project_instance):
        return CitationProjectSerializer(
            context=self.context,
            instance=project_instance.children.filter(
                Q(is_public=True)
                | Q(
                    is_public=False,
                    permissions__user=self.context.get("request").user,
                )
            ).distinct(),
            many=True,
        ).data

    """ ----- Private Methods -----"""
