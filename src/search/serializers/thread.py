from rest_framework import serializers

from discussion.models import Thread


class ThreadDocumentSerializer(serializers.ModelSerializer):
    comment_count = serializers.SerializerMethodField()
    created_by_author_profile = serializers.SerializerMethodField()
    paper = serializers.SerializerMethodField()
    paper_title = serializers.SerializerMethodField()
    score = serializers.SerializerMethodField()
    plain_text = serializers.SerializerMethodField()

    class Meta(object):
        model = Thread
        fields = [
            'id',
            'comment_count',
            'created_by_author_profile',
            'created_date',
            'is_public',
            'is_removed',
            'paper',
            'paper_title',
            'score',
            'title',
            'updated_date',
            'plain_text',
        ]
        read_only_fields = fields

    def get_comment_count(self, document):
        return document.comment_count

    def get_created_by_author_profile(self, document):
        if document.created_by_author_profile is not None:
            return document.created_by_author_profile.to_dict()

    def get_paper(self, document):
        return document.paper

    def get_paper_title(self, document):
        return document.paper_title

    def get_score(self, document):
        return document.score

    def get_text(self, document):
        return document.text

    def get_plain_text(self, document):
        return document.plain_text
