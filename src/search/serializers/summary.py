import json
from rest_framework import serializers

from summary.models import Summary


class SummaryDocumentSerializer(
    serializers.ModelSerializer,
):
    summary = serializers.SerializerMethodField()

    class Meta(object):
        model = Summary
        fields = [
            'id',
            'summary',
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
