# TODO: Refactor to remove drf
from django_elasticsearch_dsl_drf.serializers import DocumentSerializer
from rest_framework import serializers

from paper.models import Paper


class PaperDocumentSerializer(serializers.ModelSerializer):
    authors = serializers.SerializerMethodField()
    discussion_count = serializers.SerializerMethodField()
    hubs = serializers.SerializerMethodField()
    score = serializers.SerializerMethodField()
    summary = serializers.SerializerMethodField()
    title = serializers.SerializerMethodField()
    tagline = serializers.SerializerMethodField()

    class Meta(object):
        model = Paper
        fields = [
            'id',
            'authors',
            'discussion_count',
            'doi',
            'hubs',
            'paper_publish_date',
            'publication_type',
            'score',
            'summary',
            'tagline',
            'title',
            'url',
        ]

        def get_authors(self, document):
            return document.authors

        def get_discussion_count(self, document):
            return document.discussion_count

        def get_hubs(self, document):
            return document.hubs

        def get_score(self, document):
            return document.score

        def get_summary(self, document):
            return document.summary

        def get_title(self, document):
            return document.title

        def get_tagline(self, document):
            return document.tagline
