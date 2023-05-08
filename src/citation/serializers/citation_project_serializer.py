from rest_framework.serializers import (
    CurrentUserDefault,
    HiddenField,
    ModelSerializer,
    SerializerMethodField,
)

from citation.models import CitationProject


class CitationProjectSerializer(ModelSerializer):
    # HiddenField doesn't update instance if the field is not empty
    created_by = HiddenField(default=CurrentUserDefault())
    updated_by = HiddenField(default=CurrentUserDefault())
    get_current_user_has_access = SerializerMethodField(read_only=True)
    children = SerializerMethodField()

    class Meta:
        model = CitationProject
        fields = "__all__"

    """ ----- Django Method Overrides -----"""

    """ ----- Serializer Methods -----"""

    def get_current_user_has_access(self, project_instance):
        try:
            current_user = self.context.get("request").user
            return project_instance.get_current_user_has_access(current_user)
        except Exception as error:
            pass
    
    def get_children(self, rh_comment):
        return CitationProjectSerializer(
            instance=rh_comment.children,
            many=True,
        ).data

    """ ----- Private Methods -----"""
