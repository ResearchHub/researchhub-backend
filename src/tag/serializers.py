from rest_framework.serializers import ModelSerializer

from researchhub.serializers import DynamicModelFieldSerializer
from tag.models import Concept


class SimpleConceptSerializer(ModelSerializer):
    class Meta:
        model = Concept
        fields = "__all__"


class DynamicConceptSerializer(DynamicModelFieldSerializer):
    class Meta:
        model = Concept
        fields = "__all__"
