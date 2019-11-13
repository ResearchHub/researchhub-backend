from rest_framework import serializers

from user.models import Author


class AuthorDocumentSerializer(serializers.ModelSerializer):
    profile_image = serializers.SerializerMethodField()
    university = serializers.SerializerMethodField()

    class Meta(object):
        model = Author
        fields = [
            'id',
            'first_name',
            'last_name',
            'profile_image',
            'university'
        ]
        read_only_fields = fields

    def get_profile_image(self, document):
        if document.profile_image is not None:
            return document.profile_image

    def get_university(self, document):
        if document.university is not None:
            return document.university.to_dict()
