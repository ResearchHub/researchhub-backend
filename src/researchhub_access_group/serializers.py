from rest_framework.serializers import ModelSerializer, SerializerMethodField

from researchhub.serializers import DynamicModelFieldSerializer
from researchhub_access_group.models import Permission


class PermissionSerializer(ModelSerializer):
    class Meta:
        model = Permission
        fields = "__all__"


class DynamicPermissionSerializer(DynamicModelFieldSerializer):
    organization = SerializerMethodField()
    user = SerializerMethodField()
    source = SerializerMethodField()

    class Meta:
        model = Permission
        fields = "__all__"

    def get_organization(self, permission):
        from user.serializers import DynamicOrganizationSerializer

        context = self.context
        _context_fields = context.get("rag_dps_get_organization", {})
        organization = permission.organization

        if not organization:
            return None

        serializer = DynamicOrganizationSerializer(
            organization, context=context, **_context_fields
        )
        return serializer.data

    def get_user(self, permission):
        from user.serializers import DynamicUserSerializer

        context = self.context
        _context_fields = context.get("rag_dps_get_user", {})

        user = permission.user
        if not user:
            return None

        serializer = DynamicUserSerializer(user, context=context, **_context_fields)
        return serializer.data

    def get_source(self, permission):
        from hub.models import Hub
        from user.models import Organization

        context = self.context
        _context_fields = context.get("rag_dps_get_source", {})

        source = permission.source
        if isinstance(source, Hub):
            from hub.serializers import DynamicHubSerializer

            serializer = DynamicHubSerializer(
                source, context=context, **_context_fields
            )
        elif isinstance(source, Organization):
            from user.serializers import DynamicOrganizationSerializer

            serializer = DynamicOrganizationSerializer(
                source, context=context, **_context_fields
            )
        else:
            return None

        return serializer.data
