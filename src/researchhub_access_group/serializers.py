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

        # Prevent circular reference by always excluding editor_of field
        _context_fields = dict(
            _context_fields
        )  # Make a copy to avoid modifying original
        exclude_fields = _context_fields.get("_exclude_fields", [])

        if exclude_fields != "__all__":
            # Ensure it's a list and editor_of is in it
            if not isinstance(exclude_fields, list):
                exclude_fields = []
            if "editor_of" not in exclude_fields:
                exclude_fields.append("editor_of")
            _context_fields["_exclude_fields"] = exclude_fields

        serializer = DynamicUserSerializer(user, context=context, **_context_fields)
        return serializer.data

    def get_source(self, permission):
        from hub.models import Hub
        from user.models import Organization

        context = self.context
        # Hardcoding exclude for now
        _context_fields = context.get(
            "rag_dps_get_source", {"_exclude_fields": "__all__"}
        )

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
