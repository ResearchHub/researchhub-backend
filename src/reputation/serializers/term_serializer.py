from rest_framework import serializers

from reputation.models import Term
from researchhub.serializers import DynamicModelFieldSerializer


class TermSerializer(serializers.ModelSerializer):
    class Meta:
        model = Term
        fields = "__all__"


class DynamicTermSerializer(DynamicModelFieldSerializer):
    class Meta:
        model = Term
        fields = "__all__"
