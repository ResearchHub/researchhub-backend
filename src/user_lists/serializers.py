from rest_framework import serializers
from utils.serializers import DefaultAuthenticatedSerializer

from .models import List


class ListSerializer(DefaultAuthenticatedSerializer):
    class Meta:
        model = List
        fields = [
            "id",
            "name",
            "is_public",
            "created_date",
            "updated_date",
            "created_by",
        ]
        read_only_fields = ["id", "created_date", "updated_date", "created_by"]

