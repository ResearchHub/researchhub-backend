from rest_framework import serializers

from discussion.models import Thread


class ThreadDocumentSerializer(serializers.ModelSerializer):
    paper = serializers.SerializerMethodField()
    text = serializers.SerializerMethodField()

    class Meta(object):
        model = Thread
        fields = [
            'id',
            'created_date',
            'is_public',
            'is_removed',
            'paper',
            'text',
            'title',
            'updated_date',
        ]
        read_only_fields = fields

    def get_paper(self, document):
        return document.paper

    def get_text(self, document):
        return document.text
