from django_elasticsearch_dsl_drf.serializers import DocumentSerializer
from rest_framework import serializers

from paper.models import Paper
from search.documents.paper import PaperDocument
from user.models import User
from user.serializers import UserSerializer
from utils.sentry import log_error


class PaperDocumentSerializer(DocumentSerializer):
    authors = serializers.SerializerMethodField()
    slug = serializers.SerializerMethodField()
    highlight = serializers.SerializerMethodField()
    unified_document_id = serializers.SerializerMethodField()
    uploaded_by = serializers.SerializerMethodField()
    uploaded_date = serializers.SerializerMethodField()
    is_highly_cited = serializers.SerializerMethodField()
    paper_publish_year = serializers.SerializerMethodField()
    citation_percentile = serializers.SerializerMethodField()
    citations = serializers.SerializerMethodField()
    score = serializers.SerializerMethodField()
    es_score = serializers.SerializerMethodField()
    reviews = serializers.SerializerMethodField()

    class Meta(object):
        document = PaperDocument
        fields = [
            "abstract",
            "authors",
            "can_display_pdf_license",
            "citation_percentile",
            "citations",
            "completeness_status",
            "discussion_count",
            "doi",
            "es_score",
            "external_source",
            "hot_score",
            "hubs_flat",
            "hubs",
            "id",
            "is_highly_cited",
            "oa_status",
            "paper_publish_date",
            "paper_publish_year",
            "paper_title",
            "pdf_license",
            "raw_authors",
            "score",
            "slug",
            "title",
            "unified_document_id",
        ]

    def get_authors(self, hit):
        return hit.to_dict().get("authors", [])

    def get_es_score(self, obj):
        return obj.meta.score

    def get_is_highly_cited(self, hit):
        is_highly_cited = False
        try:
            paper = Paper.objects.get(id=hit["id"])
            is_highly_cited = paper.is_highly_cited
        except Exception:
            pass

        return is_highly_cited

    def get_score(self, hit):
        score = 0
        try:
            paper = Paper.objects.get(id=hit["id"])
            score = paper.unified_document.score
        except Exception as e:
            pass

        return score

    def get_highlight(self, obj):
        try:
            if hasattr(obj.meta, "highlight"):
                return obj.meta.highlight.__dict__["_d_"]
            return {}
        except Exception as e:
            log_error(e, "Paper is missing highlight")

    def get_paper_publish_year(self, hit):
        publish_year = None
        try:
            publish_year = hit["paper_publish_year"]
        except Exception as e:
            pass

        return publish_year

    def get_citations(self, hit):
        citations = None
        try:
            citations = hit["citations"]
        except Exception as e:
            pass

        return citations

    def get_citation_percentile(self, hit):
        citation_percentile = None
        try:
            citation_percentile = hit["citation_percentile"]
        except Exception as e:
            pass

        return citation_percentile

    def get_slug(self, hit):
        try:
            paper = Paper.objects.get(id=hit["id"])
            slug = paper.slug
            return slug
        except Exception as e:
            log_error(e, "Paper is missing slug")

    def get_unified_document_id(self, paper):
        try:
            obj = Paper.objects.get(id=paper.id)
            return obj.unified_document.id
        except Exception as e:
            log_error(e, "Paper is missing unified_document")

    def get_reviews(self, hit):
        reviews = {"avg": 0, "count": 0}

        try:
            paper = Paper.objects.get(id=hit["id"])
            if paper.unified_document.reviews.exists():
                reviews = paper.unified_document.get_review_details()
        except Exception:
            pass

        return reviews

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
