from rest_framework import serializers

from user.models import University


class UniversityDocumentSerializer(serializers.ModelSerializer):

    class Meta(object):
        model = University
        fields = [
            'id',
            'name',
            'country',
            'state',
            'city',
        ]
        read_only_fields = fields
