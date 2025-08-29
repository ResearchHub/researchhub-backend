from opensearchpy import Q
from rest_framework.filters import BaseFilterBackend


class BaseSearchFilterBackend(BaseFilterBackend):
    """
    Base class for Elasticsearch filter backends.
    """

    def filter_queryset(self, request, queryset, view):
        """
        Return a filtered queryset.
        """
        raise NotImplementedError("Subclasses must implement filter_queryset()")


class SearchFilterBackend(BaseSearchFilterBackend):
    """
    Filter backend for full-text search.
    Replaces CompoundSearchFilterBackend from django_elasticsearch_dsl_drf.
    """

    search_param = "search"

    def get_search_query(self, request, view):
        """
        Get search query from request parameters.
        """
        return request.query_params.get(self.search_param, "").strip()

    def filter_queryset(self, request, queryset, view):
        """
        Filter queryset based on search query.
        """
        search_query = self.get_search_query(request, view)
        if not search_query:
            return queryset

        # Get search fields from view
        search_fields = getattr(view, "search_fields", {})
        if not search_fields:
            return queryset

        # Build multi-match query
        queries = []
        for field, options in search_fields.items():
            if isinstance(options, dict):
                field_name = options.get("field", field)
                boost = options.get("boost", 1)
            else:
                field_name = field
                boost = 1

            queries.append(
                Q("match", **{field_name: {"query": search_query, "boost": boost}})
            )

        if queries:
            combined_query = queries[0]
            for query in queries[1:]:
                combined_query = combined_query | query
            queryset = queryset.query(combined_query)

        return queryset


class OrderingFilterBackend(BaseSearchFilterBackend):
    """
    Filter backend for ordering/sorting.
    Replaces OrderingFilterBackend from django_elasticsearch_dsl_drf.
    """

    ordering_param = "ordering"

    def get_ordering(self, request, view):
        """
        Get ordering from request parameters.
        """
        ordering = request.query_params.get(self.ordering_param, "")
        if ordering:
            return [field.strip() for field in ordering.split(",")]

        # Fall back to default ordering
        return getattr(view, "ordering", None)

    def filter_queryset(self, request, queryset, view):
        """
        Order queryset based on ordering parameter.
        """
        ordering = self.get_ordering(request, view)
        if not ordering:
            return queryset

        # Apply sorting
        for field in ordering:
            if field.startswith("-"):
                queryset = queryset.sort({field[1:]: {"order": "desc"}})
            else:
                queryset = queryset.sort({field: {"order": "asc"}})

        return queryset


class FilteringFilterBackend(BaseSearchFilterBackend):
    """
    Filter backend for field-based filtering.
    Replaces FilteringFilterBackend from django_elasticsearch_dsl_drf.
    """

    def get_filter_fields(self, view):
        """
        Get filterable fields from view.
        """
        return getattr(view, "filter_fields", {})

    def filter_queryset(self, request, queryset, view):
        """
        Filter queryset based on field values.
        """
        filter_fields = self.get_filter_fields(view)
        if not filter_fields:
            return queryset

        for field_name, field_config in filter_fields.items():
            param_name = field_name
            if isinstance(field_config, dict):
                param_name = field_config.get("field", field_name)

            value = request.query_params.get(param_name)
            if value is not None:
                # Handle multiple values (comma-separated)
                if "," in value:
                    values = [v.strip() for v in value.split(",")]
                    queryset = queryset.filter("terms", **{field_name: values})
                else:
                    queryset = queryset.filter("term", **{field_name: value})

        return queryset


class FacetedSearchFilterBackend(BaseSearchFilterBackend):
    """
    Filter backend for faceted search.
    Replaces FacetedSearchFilterBackend from django_elasticsearch_dsl_drf.
    """

    facets_param = "facets"

    def get_facets(self, request, view):
        """
        Get facets configuration from view.
        """
        return getattr(view, "faceted_search_fields", {})

    def filter_queryset(self, request, queryset, view):
        """
        Add facets/aggregations to queryset.
        """
        facets = self.get_facets(request, view)
        if not facets:
            return queryset

        # Check if facets are requested
        requested_facets = request.query_params.get(self.facets_param, "")
        if not requested_facets:
            return queryset

        requested_facet_names = [f.strip() for f in requested_facets.split(",")]

        for facet_name in requested_facet_names:
            if facet_name in facets:
                facet_config = facets[facet_name]
                if isinstance(facet_config, dict):
                    field = facet_config.get("field", facet_name)
                    facet_type = facet_config.get("type", "terms")
                else:
                    field = facet_name
                    facet_type = "terms"

                # Add aggregation
                if facet_type == "terms":
                    queryset.aggs.bucket(facet_name, "terms", field=field, size=20)
                elif facet_type == "date_histogram":
                    queryset.aggs.bucket(
                        facet_name, "date_histogram", field=field, interval="month"
                    )

        return queryset


class HighlightBackend(BaseSearchFilterBackend):
    """
    Filter backend for search result highlighting.
    Replaces HighlightBackend from django_elasticsearch_dsl_drf.
    """

    highlight_param = "highlight"

    def get_highlight_fields(self, view):
        """
        Get fields to highlight from view.
        """
        return getattr(view, "highlight_fields", {})

    def filter_queryset(self, request, queryset, view):
        """
        Add highlighting to queryset.
        """
        # Check if highlighting is requested
        if not request.query_params.get(self.highlight_param):
            return queryset

        highlight_fields = self.get_highlight_fields(view)
        if not highlight_fields:
            return queryset

        # Configure highlighting
        highlight_options = {
            "pre_tags": ["<mark>"],
            "post_tags": ["</mark>"],
            "fields": {},
        }

        for field_name, field_config in highlight_fields.items():
            if isinstance(field_config, dict):
                highlight_options["fields"][field_name] = field_config
            else:
                highlight_options["fields"][field_name] = {}

        queryset = queryset.highlight(**highlight_options)

        return queryset


class DefaultOrderingFilterBackend(OrderingFilterBackend):
    """
    Apply default ordering if no ordering is specified.
    Replaces DefaultOrderingFilterBackend from django_elasticsearch_dsl_drf.
    """

    def get_ordering(self, request, view):
        """
        Get ordering, using default if not specified in request.
        """
        param_ordering = super().get_ordering(request, view)
        if param_ordering:
            return param_ordering

        # Use default ordering from view
        return getattr(view, "ordering", None)


class PostFilterFilteringFilterBackend(FilteringFilterBackend):
    """
    Post-filter filtering backend (applied after aggregations).
    Replaces PostFilterFilteringFilterBackend from django_elasticsearch_dsl_drf.
    """

    def filter_queryset(self, request, queryset, view):
        """
        Apply post_filter instead of filter for aggregations.
        """
        filter_fields = self.get_filter_fields(view)
        if not filter_fields:
            return queryset

        post_filters = []

        for field_name, field_config in filter_fields.items():
            param_name = field_name
            if isinstance(field_config, dict):
                param_name = field_config.get("field", field_name)

            value = request.query_params.get(param_name)
            if value is not None:
                # Handle multiple values (comma-separated)
                if "," in value:
                    values = [v.strip() for v in value.split(",")]
                    post_filters.append(Q("terms", **{field_name: values}))
                else:
                    post_filters.append(Q("term", **{field_name: value}))

        if post_filters:
            combined_filter = post_filters[0]
            for filter_q in post_filters[1:]:
                combined_filter = combined_filter & filter_q
            queryset = queryset.post_filter(combined_filter)

        return queryset


class SuggesterFilterBackend(BaseSearchFilterBackend):
    """
    Filter backend for search suggestions/autocomplete.
    Replaces SuggesterFilterBackend from django_elasticsearch_dsl_drf.
    """

    suggest_param = "suggest"

    def get_suggester_fields(self, view):
        """
        Get suggester configuration from view.
        """
        return getattr(view, "suggester_fields", {})

    def filter_queryset(self, request, queryset, view):
        """
        Add suggestions to search.
        """
        # First check for simple suggest parameter
        suggest_query = request.query_params.get(self.suggest_param, "").strip()

        # Get suggester fields from view
        suggester_fields = self.get_suggester_fields(view)
        if not suggester_fields:
            return queryset

        # Check for django-elasticsearch-dsl-drf style parameters
        # Format: field_name__completion=value
        suggestions_added = False
        for suggester_name, field_config in suggester_fields.items():
            # Check if this specific field was requested with __completion suffix
            field_param = f"{suggester_name}__completion"
            field_value = request.query_params.get(field_param, "")

            # Use field-specific value if provided, otherwise use general suggest query
            query_value = field_value if field_value else suggest_query

            if not query_value:
                continue

            if isinstance(field_config, dict):
                field = field_config.get("field", suggester_name)
                suggester_type = field_config.get("type", "phrase")
            else:
                field = field_config
                suggester_type = "phrase"

            if suggester_type == "phrase":
                queryset = queryset.suggest(
                    suggester_name, query_value, phrase={"field": field}
                )
            elif suggester_type == "term":
                queryset = queryset.suggest(
                    suggester_name, query_value, term={"field": field}
                )
            elif suggester_type == "completion":
                # Truncate query to 50 characters for ES completion suggester
                truncated_query = query_value[:50]
                queryset = queryset.suggest(
                    suggester_name, truncated_query, completion={"field": field}
                )

            suggestions_added = True

        return queryset
