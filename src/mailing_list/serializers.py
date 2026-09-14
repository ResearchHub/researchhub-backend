from rest_framework import serializers


class EmailUnsubscribeSerializer(serializers.Serializer):
    """
    Used to validate the payload for unsubscribing an email using a signed code.
    """

    code = serializers.CharField(allow_blank=False, trim_whitespace=False)
