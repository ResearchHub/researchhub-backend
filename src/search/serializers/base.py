from rest_framework import serializers


class BaseModelSerializer(serializers.ModelSerializer):
    highlight = serializers.SerializerMethodField()

    class Meta:
        abstract = True
        fields = []
        read_only_fields = fields

    def get_highlight(self, obj):
        if hasattr(obj.meta, 'highlight'):
            return obj.meta.highlight.__dict__['_d_']
        return {}
