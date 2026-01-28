import logging

from opensearchpy import Q, Search

logger = logging.getLogger(__name__)


class MatchBoolPrefixBackend:
    """
    Backend for constructing and executing match_bool_prefix queries.
    Optimized for autocomplete use cases with 2+ word queries.
    """

    # Minimum should match configuration for match_bool_prefix queries.
    # Format: "2<70%" means at least 2 terms OR 70% of terms must match
    # (whichever is higher). This prevents single-word matches on multi-word
    # queries while allowing flexibility for longer queries.
    MINIMUM_SHOULD_MATCH = "2<70%"

    @classmethod
    def execute_search(
        cls,
        index_name: str,
        field_name: str,
        query: str,
        limit: int = 10,
    ):
        """
        Execute a match_bool_prefix search query with fuzziness support.

        Args:
            index_name: The Elasticsearch index name
            field_name: The field to search
            query: The search query string
            limit: Maximum number of results to return

        Returns:
            Response: Elasticsearch search response
        """
        try:
            # match_bool_prefix with fuzziness for earlier terms
            # Note: This is only called for 2+ word queries (validated by caller)
            # Fuzziness applies to all terms except the last (prefix) term
            query_params = {
                "query": query,
                "minimum_should_match": cls.MINIMUM_SHOULD_MATCH,
                "fuzziness": "AUTO",
            }
            search_query = Q("match_bool_prefix", **{field_name: query_params})
            search = Search(index=index_name).query(search_query)[:limit]
            return search.execute()
        except Exception as e:
            logger.error(
                f"Error executing match_bool_prefix query on {index_name}: {str(e)}"
            )
            raise
