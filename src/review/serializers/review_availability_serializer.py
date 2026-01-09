from rest_framework import serializers


class ReviewAvailabilitySerializer(serializers.Serializer):
    can_review = serializers.BooleanField()
    available_at = serializers.DateTimeField(allow_null=True)

