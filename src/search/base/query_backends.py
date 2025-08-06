"""
Base query backend classes for custom search implementations.
"""

from elasticsearch_dsl import Q


class BaseSearchQueryBackend:
    """
    Base search query backend.
    Replaces django_elasticsearch_dsl_drf.filter_backends.search.query_backends.BaseSearchQueryBackend
    """

    def __init__(self, params=None):
        """
        Initialize the backend with search parameters.
        """
        self.params = params or {}

    def get_query(self, query_string, fields=None, options=None):
        """
        Build and return the search query.

        Args:
            query_string (str): The search string
            fields (list): List of fields to search
            options (dict): Additional query options

        Returns:
            Q: Elasticsearch DSL query object
        """
        raise NotImplementedError("Subclasses must implement get_query()")

    def filter(self, queryset, query_string, fields=None, options=None):
        """
        Apply the query to the queryset.

        Args:
            queryset: Elasticsearch search object
            query_string (str): The search string
            fields (list): List of fields to search
            options (dict): Additional query options

        Returns:
            Search: Modified search object
        """
        query = self.get_query(query_string, fields, options)
        if query:
            return queryset.query(query)
        return queryset
