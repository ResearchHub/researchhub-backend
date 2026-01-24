import logging

from opensearchpy import Q, Search

logger = logging.getLogger(__name__)


class MatchBoolPrefixBackend:
    """
    Backend for constructing and executing match_bool_prefix queries.
    Optimized for autocomplete use cases with 2+ word queries.
    """

    @staticmethod
    def construct_query(
        field_name: str,
        query: str,
        words_to_skip: int = 2,
    ) -> Q:
        """
        Construct a match_bool_prefix query.

        Args:
            field_name: The field to search (e.g., "title", "paper_title")
            query: The search query string
            words_to_skip: Number of words that can be skipped from matching.
                Calculates minimum_should_match as (number of words - words_to_skip).
                Default is 2, which allows skipping 2 words
                (e.g., the last prefix term + 1 more).

        Returns:
            Q: OpenSearch Q object with match_bool_prefix query
        """
        query_params = {"query": query}

        num_words = len(query.split())
        if num_words > words_to_skip:
            # Require (number of words - words_to_skip) terms to match
            # Default: words_to_skip=2 allows skipping 2 words
            # (e.g., last prefix term + 1 more)
            minimum_should_match = num_words - words_to_skip
            query_params["minimum_should_match"] = minimum_should_match

        return Q("match_bool_prefix", **{field_name: query_params})

    @staticmethod
    def execute_search(
        index_name: str,
        field_name: str,
        query: str,
        limit: int = 10,
        enable_fuzzy_fallback: bool = True,
        words_to_skip: int = 2,
    ):
        """
        Execute a match_bool_prefix search query with optional fuzzy fallback.

        Args:
            index_name: The Elasticsearch index name
            field_name: The field to search
            query: The search query string
            limit: Maximum number of results to return
            enable_fuzzy_fallback: If True, fall back to fuzzy query if no results
            words_to_skip: Number of words that can be skipped from matching.
                Calculates minimum_should_match as (number of words - words_to_skip).
                Default is 2, which allows skipping 2 words
                (e.g., the last prefix term + 1 more).

        Returns:
            Response: Elasticsearch search response
        """
        try:
            # Try match_bool_prefix first (fast, exact match)
            search_query = MatchBoolPrefixBackend.construct_query(
                field_name, query, words_to_skip
            )
            search = Search(index=index_name).query(search_query)[:limit]
            response = search.execute()

            # If no results and fuzzy fallback enabled, try fuzzy matching
            if enable_fuzzy_fallback and response.hits.total.value == 0:
                logger.debug(
                    f"No results from match_bool_prefix for '{query}', "
                    f"trying fuzzy fallback"
                )
                # Use fuzzy match for typo tolerance
                fuzzy_query = Q(
                    "match",
                    **{
                        field_name: {
                            "query": query,
                            "fuzziness": "AUTO",
                            "operator": "and",
                        }
                    },
                )
                fuzzy_search = Search(index=index_name).query(fuzzy_query)[:limit]
                return fuzzy_search.execute()

            return response
        except Exception as e:
            logger.error(
                f"Error executing match_bool_prefix query on {index_name}: {str(e)}"
            )
            raise
