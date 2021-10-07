from rest_framework.serializers import ModelSerializer, SerializerMethodField

from researchhub_access_group.models import Permission
from researchhub.serializers import DynamicModelFieldSerializer


class PermissionSerializer(ModelSerializer):
    class Meta:
        model = Permission
        fields = '__all__'


class DynamicPermissionSerializer(DynamicModelFieldSerializer):
    class Meta:
        model = Permission
        fields = '__all__'
