from rest_framework import serializers

from summary.models import Summary


class SummaryDocumentSerializer(
    serializers.ModelSerializer,
):
    summary_plain_text = serializers.SerializerMethodField()

    class Meta(object):
        model = Summary
        fields = [
            'id',
            'summary_plain_text',
            # 'proposed_by',
            # 'previous',
            # 'paper',
            'approved',
            # 'approved_by',
            'approved_date',
            'created_date',
            'updated_date',
        ]
        read_only_fields = fields

    def get_summary(self, obj):
        return obj.summary

    def get_summary_plain_text(self, document):
        return document.summary_plain_text
