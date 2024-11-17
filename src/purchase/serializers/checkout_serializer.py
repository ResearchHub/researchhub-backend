from rest_framework import serializers

import paper


class CheckoutSerializer(serializers.Serializer):
    success_url = serializers.CharField(required=True)
    failure_url = serializers.CharField(required=True)
    paper = serializers.PrimaryKeyRelatedField(
        queryset=paper.models.Paper.objects.all(),
        required=True,
    )
