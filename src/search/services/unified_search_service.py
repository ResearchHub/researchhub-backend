"""
Unified search service for searching across documents (papers/posts).
"""

import logging
import time
from typing import Any

from opensearchpy import Q, Search

from search.base.utils import seconds_to_milliseconds
from search.documents.paper import PaperDocument
from search.documents.post import PostDocument
from search.services.search_config import PopularityConfig
from search.services.search_error_utils import handle_search_error
from search.services.unified_search_query_builder import UnifiedSearchQueryBuilder
from utils.doi import DOI

logger = logging.getLogger(__name__)


class UnifiedSearchService:

    SORT_RELEVANCE = "relevance"
    SORT_NEWEST = "newest"

    VALID_SORT_OPTIONS = [SORT_RELEVANCE, SORT_NEWEST]

    def __init__(self):
        self.paper_index = PaperDocument._index._name
        self.post_index = PostDocument._index._name
        self.query_builder = UnifiedSearchQueryBuilder()

    def search(
        self,
        query: str,
        page: int = 1,
        page_size: int = 10,
        sort: str = SORT_RELEVANCE,
        request=None,
    ) -> dict[str, Any]:

        start_time = time.time()

        # Validate sort option
        if sort not in self.VALID_SORT_OPTIONS:
            sort = self.SORT_RELEVANCE

        # Calculate offset
        offset = (page - 1) * page_size

        # If query is a DOI and there is an exact match, return only that result
        try:
            if DOI.is_doi(query):
                normalized_doi = DOI.normalize_doi(query)
                doi_result = self._search_documents_by_doi(normalized_doi)
                if doi_result["count"] > 0:
                    execution_time = time.time() - start_time
                    return {
                        "count": doi_result["count"],
                        "next": None,
                        "previous": None,
                        "documents": doi_result["results"],
                        "people": [],
                        "aggregations": {},
                        "execution_time_ms": seconds_to_milliseconds(execution_time),
                    }
        except Exception:
            # Fallback to regular flow if DOI parsing/search fails
            pass

        # Search documents (papers and posts)
        document_results = self._search_documents(query, offset, page_size, sort)

        # Total count is just document count
        total_count = document_results["count"]

        # Calculate pagination URLs
        next_url = None
        previous_url = None

        if request:
            # Check if there are more results
            if page * page_size < total_count:
                next_url = self._build_page_url(
                    request, query, page + 1, page_size, sort
                )

            # Check if there are previous results
            if page > 1:
                previous_url = self._build_page_url(
                    request, query, page - 1, page_size, sort
                )

        execution_time = time.time() - start_time

        return {
            "count": total_count,
            "next": next_url,
            "previous": previous_url,
            "documents": document_results["results"],
            "people": [],
            "aggregations": {},
            "execution_time_ms": seconds_to_milliseconds(execution_time),
        }

    def _build_author_filter(self) -> Q:
        # Use exists queries on nested author fields - these only match if the array
        # has at least one element with that field
        return Q(
            "bool",
            should=[
                Q("exists", field="raw_authors.full_name"),
                Q("exists", field="authors.full_name"),
            ],
            minimum_should_match=1,
        )

    def _search_documents(
        self,
        query: str,
        offset: int,
        limit: int,
        sort: str,
        popularity_config: PopularityConfig | None = None,
    ) -> dict[str, Any]:

        # Create multi-index search for papers and posts
        search = Search(index=[self.paper_index, self.post_index])

        # Build query with field boosting and popularity signals
        # Uses function_score to combine text relevance with engagement metrics
        if popularity_config is None:
            popularity_config = PopularityConfig()

        query_obj = self.query_builder.build_document_query_with_popularity(
            query, popularity_config
        )

        # Wrap query with author filter to exclude documents without authors
        author_filter = self._build_author_filter()
        filtered_query = Q("bool", must=[query_obj], filter=[author_filter])
        search = search.query(filtered_query)

        search = self._apply_highlighting(search)

        search = self._apply_sort(search, sort)

        search = search[offset : offset + limit]

        # Optimize query performance
        search = search.extra(
            track_total_hits=True,
            timeout="5s",
        )

        # Source filtering for performance
        search = search.source(
            [
                "id",
                "paper_title",
                "title",
                "abstract",
                "renderable_text",
                "raw_authors",
                "authors",
                "created_date",
                "paper_publish_date",
                "citations",
                "hubs",
                "doi",
                "slug",
                "score",
                "hot_score",
                "discussion_count",
                "unified_document_id",
                "document_type",
            ]
        )

        # Execute search
        try:
            response = search.execute()
            self._log_first_hit_index(response)
        except Exception as e:
            handle_search_error(e, query, offset, limit, sort)
            return {"results": [], "count": 0}

        results = self._process_document_results(response)

        return {
            "results": results,
            "count": response.hits.total.value,
        }

    def _log_first_hit_index(self, response) -> None:
        """Log the index of the first hit if results are available."""
        if response.hits.total.value > 0:
            first_hit_index = response.hits[0].meta.index if response.hits else "N/A"
            logger.info(f"First hit index: {first_hit_index}")

    def _search_documents_by_doi(self, normalized_doi: str) -> dict[str, Any]:

        search = Search(index=[self.paper_index, self.post_index])

        # Build DOI query and wrap with author filter
        doi_query = Q("term", doi={"value": normalized_doi})
        author_filter = self._build_author_filter()
        filtered_query = Q("bool", must=[doi_query], filter=[author_filter])
        search = search.query(filtered_query)

        # Sort by date to get the latest version
        # Prefer updated_date if available (for posts), otherwise created_date
        # This handles both papers (created_date only) and posts (both fields)
        search = search.sort(
            {
                "_script": {
                    "type": "number",
                    "script": {
                        "source": (
                            "if (doc.containsKey('updated_date') && "
                            "!doc['updated_date'].empty) {"
                            "  return doc['updated_date'].value.toEpochMilli();"
                            "} else if (doc.containsKey('created_date') && "
                            "!doc['created_date'].empty) {"
                            "  return doc['created_date'].value.toEpochMilli();"
                            "}"
                            "return 0;"
                        ),
                        "lang": "painless",
                    },
                    "order": "desc",
                }
            }
        )

        # Source filtering for performance (match document search fields)
        search = search.source(
            [
                "id",
                "paper_title",
                "title",
                "abstract",
                "renderable_text",
                "raw_authors",
                "authors",
                "created_date",
                "updated_date",
                "paper_publish_date",
                "citations",
                "hubs",
                "doi",
                "slug",
                "score",
                "hot_score",
                "discussion_count",
                "unified_document_id",
                "document_type",
            ]
        )

        # Limit to one exact match (latest version)
        search = search[0:1]
        search = search.extra(track_total_hits=True, timeout="5s")

        try:
            response = search.execute()
        except Exception as e:
            logger.error(f"DOI search failed: {str(e)}")
            return {"results": [], "count": 0}

        results = self._process_document_results(response)
        return {"results": results, "count": response.hits.total.value}

    def _apply_highlighting(self, search: Search) -> Search:
        """
        Apply highlighting configuration to search.
        """
        highlight_fields = {
            "paper_title": {"number_of_fragments": 0},
            "title": {"number_of_fragments": 0},
            "abstract": {"fragment_size": 700, "number_of_fragments": 1},
            "renderable_text": {"fragment_size": 700, "number_of_fragments": 1},
            "raw_authors.full_name": {"number_of_fragments": 0},
            "authors.full_name": {"number_of_fragments": 0},
        }

        search = search.highlight_options(
            pre_tags=["<mark>"],
            post_tags=["</mark>"],
        )

        for field, options in highlight_fields.items():
            search = search.highlight(field, **options)

        return search

    def _apply_sort(self, search: Search, sort: str) -> Search:
        """
        Apply sorting based on sort option.
        """
        if sort == self.SORT_NEWEST:
            search = search.sort(
                "-created_date",
                {"_score": {"order": "desc"}},
            )
        else:  # SORT_RELEVANCE or default
            search = search.sort({"_score": {"order": "desc"}})

        return search

    def _extract_document_highlights(self, highlights) -> tuple[str | None, str | None]:
        """Extract snippet and matched field from document highlights."""
        if not highlights:
            return None, None

        # Priority: title > abstract/content
        if hasattr(highlights, "paper_title"):
            return highlights.paper_title[0], "title"
        if hasattr(highlights, "title"):
            return highlights.title[0], "title"
        if hasattr(highlights, "abstract"):
            return highlights.abstract[0], "abstract"
        if hasattr(highlights, "renderable_text"):
            return highlights.renderable_text[0], "content"

        return None, None

    def _build_paper_fields(self, hit) -> dict[str, Any]:
        """Build paper-specific fields for a search result."""
        raw_doi = getattr(hit, "doi", None)
        return {
            "authors": [
                {
                    "first_name": author.get("first_name", ""),
                    "last_name": author.get("last_name", ""),
                    "full_name": author.get("full_name", ""),
                }
                for author in getattr(hit, "raw_authors", [])
            ],
            "doi": DOI.normalize_doi(raw_doi) if raw_doi else None,
            "citations": getattr(hit, "citations", 0),
            "paper_publish_date": getattr(hit, "paper_publish_date", None),
            "unified_document_id": getattr(hit, "unified_document_id", None),
            "abstract": getattr(hit, "abstract", None),
        }

    def _build_post_fields(self, hit) -> dict[str, Any]:
        """Build post-specific fields for a search result."""
        return {
            "authors": [
                {
                    "first_name": author.get("first_name", ""),
                    "last_name": author.get("last_name", ""),
                    "full_name": author.get("full_name", ""),
                }
                for author in getattr(hit, "authors", [])
            ],
            "slug": getattr(hit, "slug", None),
            "document_type": getattr(hit, "document_type", None),
            "unified_document_id": getattr(hit, "unified_document_id", None),
            "renderable_text": getattr(hit, "renderable_text", None),
        }

    def _process_hubs(self, hit) -> list[dict[str, Any]]:
        """Process and format hubs from a search hit."""
        hubs = getattr(hit, "hubs", [])
        if not hubs:
            return []

        return [
            {
                "id": hub.get("id"),
                "name": hub.get("name"),
                "slug": hub.get("slug"),
            }
            for hub in hubs
        ]

    def _process_document_results(self, response) -> list[dict[str, Any]]:

        results = []

        for hit in response.hits:
            # Determine document type from index
            doc_type = "paper" if "paper" in hit.meta.index else "post"

            # Get highlights
            highlights = getattr(hit.meta, "highlight", None)
            snippet, matched_field = self._extract_document_highlights(highlights)

            # Build result object
            result = {
                "id": hit.id,
                "type": doc_type,
                "title": getattr(hit, "paper_title", None) or getattr(hit, "title", ""),
                "snippet": snippet,
                "matched_field": matched_field,
                "created_date": getattr(hit, "created_date", None),
                "score": getattr(hit, "score", 0),
                "hot_score": getattr(hit, "hot_score", 0),
                "discussion_count": getattr(hit, "discussion_count", 0),
                "_search_score": hit.meta.score,
            }

            # Add document-specific fields
            if doc_type == "paper":
                result.update(self._build_paper_fields(hit))
            else:
                result.update(self._build_post_fields(hit))

            # Add hubs
            result["hubs"] = self._process_hubs(hit)

            results.append(result)

        return results

    def _build_page_url(
        self, request, query: str, page: int, page_size: int, sort: str
    ) -> str:

        from urllib.parse import urlencode

        # Build query parameters
        params = {
            "q": query,
            "page": page,
            "page_size": page_size,
            "sort": sort,
        }

        # Build full URL
        base_url = request.build_absolute_uri(request.path)
        return f"{base_url}?{urlencode(params)}"
