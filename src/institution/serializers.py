from rest_framework.serializers import SerializerMethodField

from institution.models import Institution
from researchhub.serializers import DynamicModelFieldSerializer


class DynamicInstitutionSerializer(DynamicModelFieldSerializer):
    institutions = SerializerMethodField()

    class Meta:
        model = Institution
        fields = "__all__"
