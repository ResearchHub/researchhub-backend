from rest_framework import serializers

import paper


class CheckoutSerializer(serializers.Serializer):
    success_url = serializers.URLField(required=True)
    failure_url = serializers.URLField(required=True)
    paper = serializers.PrimaryKeyRelatedField(
        queryset=paper.models.Paper.objects.all(),
        required=True,
    )
