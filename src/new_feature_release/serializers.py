from rest_framework import serializers

from .models import NewFeatureClick


class NewFeatureClickSerializer(serializers.ModelSerializer):
    class Meta:
        fields = "__all__"
        read_only_fields = ["user"]
        model = NewFeatureClick
