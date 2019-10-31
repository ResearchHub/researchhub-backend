from rest_framework import serializers

from user.models import Author


class AuthorDocumentSerializer(serializers.ModelSerializer):
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

    def get_highlight(self, obj):
        if hasattr(obj.meta, 'highlight'):
            return obj.meta.highlight.__dict__['_d_']
        return {}
