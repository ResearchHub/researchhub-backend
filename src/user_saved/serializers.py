from rest_framework import serializers

from .models import UserSavedList


class UserSavedListSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserSavedList
        fields = ["list_name"]


class CreateListSerializer(serializers.Serializer):
    list_name = serializers.CharField(max_length=200)


class ChangeDocumentSerializer(serializers.Serializer):
    list_name = serializers.CharField(max_length=200)
    delete_flag = serializers.BooleanField()
    u_doc_id = serializers.IntegerField(required=False, allow_null=True)
    paper_id = serializers.IntegerField(required=False, allow_null=True)


class DeleteListSerializer(serializers.Serializer):
    list_name = serializers.CharField(max_length=200)
