from rest_framework.serializers import ModelSerializer, SerializerMethodField

from researchhub_access_group.models import Permission
from researchhub.serializers import DynamicModelFieldSerializer


class PermissionSerializer(ModelSerializer):
    class Meta:
        model = Permission
        fields = '__all__'


class DynamicPermissionSerializer(DynamicModelFieldSerializer):
    organization = SerializerMethodField()
    # user = SerializerMethodField()

    class Meta:
        model = Permission
        fields = '__all__'

    def get_organization(self, permission):
        from user.serializers import DynamicOrganizationSerializer

        context = self.context
        _context_fields = context.get('rag_dps_get_organization', {})
        organization = permission.owner

        if not organization:
            return None

        serializer = DynamicOrganizationSerializer(
            organization,
            context=context,
            **_context_fields
        )
        return serializer.data

    # def get_user(self, permission):
    #     from user.serializers import DynamicUserSerializer

    #     context = self.context
    #     _context_fields = context.get('rag_dps_get_user', {})

    #     org = permission.owner
    #     if not org:
    #         return None

    #     user = org.user
    #     if not user:
    #         return None

    #     serializer = DynamicUserSerializer(
    #         user,
    #         context=context,
    #         **_context_fields
    #     )
    #     return serializer.data
