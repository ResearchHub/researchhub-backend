import re

from django_elasticsearch_dsl_drf.filter_backends import (
    CompoundSearchFilterBackend,
    DefaultOrderingFilterBackend,
    FacetedSearchFilterBackend,
    FilteringFilterBackend,
    HighlightBackend,
    IdsFilterBackend,
    NestedFilteringFilterBackend,
    OrderingFilterBackend,
    PostFilterFilteringFilterBackend,
    SearchFilterBackend,
    SuggesterFilterBackend,
)
from django_elasticsearch_dsl_drf.pagination import LimitOffsetPagination
from django_elasticsearch_dsl_drf.viewsets import DocumentViewSet
from elasticsearch_dsl import Q, Search

from search.backends.multi_match_filter import MultiMatchSearchFilterBackend
from search.documents.paper import PaperDocument
from search.serializers.paper import PaperDocumentSerializer
from utils.permissions import ReadOnly


class PaperDocumentView(DocumentViewSet):
    def _is_doi(search_term):
        try:
            # Regex imported from https://stackoverflow.com/questions/27910/finding-a-doi-in-a-document-or-page
            regex = '(10[.][0-9]{4,}(?:[.][0-9]+)*/(?:(?![%"#? ])\\S)+)'
            if re.match(regex, search_term):
                return True
        except:
            pass

        return False

    document = PaperDocument
    permission_classes = [ReadOnly]
    serializer_class = PaperDocumentSerializer
    pagination_class = LimitOffsetPagination
    lookup_field = "id"
    filter_backends = [
        MultiMatchSearchFilterBackend,
        CompoundSearchFilterBackend,
        FacetedSearchFilterBackend,
        FilteringFilterBackend,
        PostFilterFilteringFilterBackend,
        DefaultOrderingFilterBackend,
        OrderingFilterBackend,
        HighlightBackend,
    ]

    search_fields = {
        "doi": {"boost": 10},
        "title": {"boost": 3},
        "raw_authors.full_name": {"boost": 3},
        "abstract": {"boost": 1},
        "external_source": {"boost": 1},
        "hubs_flat": {"boost": 1},
    }

    multi_match_search_fields = {
        "doi": {
            "condition": _is_doi,
            "options": {
                "analyzer": "keyword",
                "boost": 10,
            },
        },
        "title": {"boost": 4},
        "raw_authors.full_name": {"boost": 3},
        "abstract": {"boost": 1},
        "hubs_flat": {"boost": 1},
    }

    multi_match_options = {
        "operator": "and",
        "type": "cross_fields",
        "analyzer": "content_analyzer",
    }

    post_filter_fields = {
        "hubs": "hubs.name",
    }

    faceted_search_fields = {
        "hubs": "hubs.name",
        "paper_publish_year": {"field": "paper_publish_year", "enabled": True},
        "pdf_license": {"field": "pdf_license", "enabled": True},
        "external_source": {"field": "external_source", "enabled": True},
    }

    filter_fields = {
        "paper_publish_year": "paper_publish_year",
        "pdf_license": "pdf_license",
        "external_source": "external_source",
        "citations": "citations",
        "citation_percentile": "citation_percentile",
    }

    ordering = ("_score", "-hot_score", "-discussion_count", "-paper_publish_date")

    ordering_fields = {
        "publish_date": "paper_publish_date",
        "discussion_count": "discussion_count",
        "score": "score",
        "hot_score": "hot_score",
    }

    highlight_fields = {
        "raw_authors.full_name": {
            "field": "raw_authors",
            "enabled": True,
            "options": {
                "pre_tags": ["<mark>"],
                "post_tags": ["</mark>"],
                "fragment_size": 1000,
                "number_of_fragments": 10,
            },
        },
        "title": {
            "enabled": True,
            "options": {
                "pre_tags": ["<mark>"],
                "post_tags": ["</mark>"],
                "fragment_size": 2000,
                "number_of_fragments": 1,
            },
        },
        "abstract": {
            "enabled": True,
            "options": {
                "pre_tags": ["<mark>"],
                "post_tags": ["</mark>"],
                "fragment_size": 5000,
                "number_of_fragments": 1,
            },
        },
    }

    def get_queryset(self):
        queryset = super().get_queryset()

        boost_queries = Q(
            "function_score",
            query=Q("match_all"),
            functions=[
                # Boost papers that are COMPLETE meaning they contain a PDF and metadata
                {"filter": Q("term", completeness_status="COMPLETE"), "weight": 4},
                # Boost papers with hot_score > 0
                {
                    "script_score": {
                        "script": {
                            "source": "if (doc['hot_score'].value > 0) { return 2; } else { return 1; }",
                            "lang": "painless",
                        }
                    }
                },
                # Boost papers with abstract
                {"filter": Q("exists", field="abstract"), "weight": 3},
                # Boost papers that have a pdf which can be displayed
                {"filter": Q("term", can_display_pdf_license=True), "weight": 1},
            ],
            boost_mode="sum",
        )

        queryset = queryset.query(boost_queries)

        return queryset

    def __init__(self, *args, **kwargs):
        self.search = Search(index=["paper"])
        super(PaperDocumentView, self).__init__(*args, **kwargs)

    def _filter_queryset(self, request):
        queryset = self.search

        for backend in list(self.filter_backends):
            queryset = backend().filter_queryset(
                request,
                queryset,
                self,
            )

        return queryset
