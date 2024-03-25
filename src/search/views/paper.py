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
from elasticsearch_dsl import Search

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
    # This field will be added to the ES _score
    score_field = "score"
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
        "doi": {"boost": 3},
        "paper_title": {"boost": 3},
        "title": {"boost": 2},
        "raw_authors.full_name": {"boost": 1},
        "abstract": {"boost": 1},
        "hubs_flat": {"boost": 1},
    }

    multi_match_search_fields = {
        "doi": {
            "condition": _is_doi,
            "options": {
                "analyzer": "keyword",
            },
        },
        "paper_title": {"boost": 3},
        "title": {"boost": 2},
        "raw_authors.full_name": {"boost": 1},
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
