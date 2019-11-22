from rest_framework import serializers

from summary.models import Summary


class SummaryDocumentSerializer(serializers.ModelSerializer):
    paper = serializers.SerializerMethodField()
    paper_title = serializers.SerializerMethodField()
    summary_plain_text = serializers.SerializerMethodField()

    class Meta(object):
        model = Summary
        fields = [
            'id',
            'approved',
            'approved_date',
            'created_date',
            'updated_date',
            'paper',
            'paper_title',
            'summary_plain_text',
        ]
        read_only_fields = fields

    def get_paper(self, document):
        return document.paper

    def get_paper_title(self, document):
        return document.paper_title

    def get_summary_plain_text(self, document):
        return document.summary_plain_text
