from rest_framework import serializers

from user.models import Author


class AuthorDocumentSerializer(
    serializers.ModelSerializer
):
    university = serializers.SerializerMethodField()

    class Meta(object):
        model = Author
        fields = [
            'id',
            'first_name',
            'last_name',
            'university'
        ]
        read_only_fields = fields

    def get_university(self, document):
        if document.university is not None:
            return document.university.to_dict()
