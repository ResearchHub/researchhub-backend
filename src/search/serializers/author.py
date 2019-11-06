from rest_framework import serializers

from .mixins import HighlightSerializerMixin
from user.models import Author


class AuthorDocumentSerializer(
    serializers.ModelSerializer,
    HighlightSerializerMixin
):
    highlight = serializers.SerializerMethodField()

    class Meta(object):
        model = Author
        fields = [
            'id',
            'first_name',
            'last_name',
            'highlight',
        ]
        read_only_fields = fields
