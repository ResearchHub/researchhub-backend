from rest_framework.serializers import ModelSerializer, SerializerMethodField

from researchhub_access_group.models import ResearchhubAccessGroup
from researchhub.serializers import DynamicModelFieldSerializer


class AccessGroupSerializer(ModelSerializer):
    class Meta:
        model = ResearchhubAccessGroup
        fields = '__all__'


class DynamicAccessGroupSerializer(DynamicModelFieldSerializer):
    class Meta:
        model = ResearchhubAccessGroup
        fields = '__all__'
