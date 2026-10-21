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
        for suggester_name, field_config in suggester_fields.items():
            # Check if this specific field was requested with __completion suffix
            field_param = f"{suggester_name}__completion"
            field_value = request.query_params.get(field_param, "")

            # Use field-specific value if provided, otherwise use general suggest query
            query_value = field_value or suggest_query

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

        return queryset
