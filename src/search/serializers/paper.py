from django_elasticsearch_dsl_drf.serializers import DocumentSerializer
from rest_framework import serializers

from paper.models import Paper
from search.documents.paper import PaperDocument
from user.models import User
from user.serializers import UserSerializer
from utils.sentry import log_error


class PaperDocumentSerializer(DocumentSerializer):
    slug = serializers.SerializerMethodField()
    highlight = serializers.SerializerMethodField()
    unified_doc_id = serializers.SerializerMethodField()
    uploaded_by = serializers.SerializerMethodField()
    uploaded_date = serializers.SerializerMethodField()

    class Meta(object):
        document = PaperDocument
        fields = [
            "id",
            "authors",
            "abstract",
            "raw_authors",
            "doi",
            "hubs",
            "hubs_flat",
            "paper_publish_date",
            "oa_status",
            "pdf_license",
            "external_source",
            "slug",
            "title",
            "paper_title",
            "unified_doc_id",
            "paper_publish_year",
        ]

    def get_highlight(self, obj):
        try:
            if hasattr(obj.meta, "highlight"):
                return obj.meta.highlight.__dict__["_d_"]
            return {}
        except Exception as e:
            log_error(e, "Paper is missing highlight")

    def get_slug(self, hit):
        try:
            paper = Paper.objects.get(id=hit["id"])
            slug = paper.slug
            return slug
        except Exception as e:
            log_error(e, "Paper is missing slug")

    def get_unified_doc_id(self, paper):
        try:
            obj = Paper.objects.get(id=paper.id)
            return obj.unified_document.id
        except Exception as e:
            log_error(e, "Paper is missing unified_document")

    def get_uploaded_by(self, hit):
        try:
            paper = Paper.objects.get(id=hit["id"])
            uploaded_by = paper.uploaded_by

            if uploaded_by:
                user = User.objects.get(id=paper.uploaded_by.id)
                return UserSerializer(user, read_only=True).data
            return None
        except Exception as e:
            log_error(e, "Paper is missing uploaded_by")

    def get_uploaded_date(self, hit):
        try:
            paper = Paper.objects.get(id=hit["id"])
            return paper.uploaded_date
        except Exception as e:
            log_error(e, "Paper is missing uploaded_date")


class CrossrefPaperSerializer(serializers.Serializer):
    # TODO: Add description
    id = serializers.IntegerField()
    meta = serializers.JSONField()
    title = serializers.CharField()
    paper_title = serializers.CharField()
    doi = serializers.CharField()
    url = serializers.URLField()
