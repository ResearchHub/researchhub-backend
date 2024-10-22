from rest_framework import serializers


class PaperUploadSerializer(serializers.Serializer):
    """
    Serializer for uploading a paper.
    Used to validate request data.
    """

    filename = serializers.CharField(required=True)
