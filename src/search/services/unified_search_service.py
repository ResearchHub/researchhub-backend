import time
from typing import Any

from opensearchpy import Q, Search

from search.base.utils import seconds_to_milliseconds
from search.documents.post import PostDocument
from search.services.search_error_utils import handle_search_error
from search.services.unified_search_query_builder import (
    PopularityConfig,
    UnifiedSearchQueryBuilder,
)


class UnifiedSearchService:
    SORT_RELEVANCE = "relevance"
    SORT_NEWEST = "newest"

    VALID_SORT_OPTIONS = [SORT_RELEVANCE, SORT_NEWEST]

    def __init__(self):
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

        if sort not in self.VALID_SORT_OPTIONS:
            sort = self.SORT_RELEVANCE

        offset = (page - 1) * page_size

        document_results = self._search_documents(query, offset, page_size, sort)
        total_count = document_results["count"]

        next_url = None
        previous_url = None

        if request:
            if page * page_size < total_count:
                next_url = self._build_page_url(
                    request, query, page + 1, page_size, sort
                )
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
        return Q("exists", field="authors.full_name")

    def _search_documents(
        self,
        query: str,
        offset: int,
        limit: int,
        sort: str,
        popularity_config: PopularityConfig | None = None,
    ) -> dict[str, Any]:
        search = Search(index=self.post_index)
        config = popularity_config or self.query_builder.popularity_config
        query_obj = self.query_builder.build_document_query_with_popularity(
            query, config
        )
        author_filter = self._build_author_filter()
        filtered_query = Q("bool", must=[query_obj], filter=[author_filter])
        search = search.query(filtered_query)

        search = self._apply_highlighting(search)

        search = self._apply_sort(search, sort)

        search = search[offset : offset + limit]
        search = search.extra(track_total_hits=True, timeout="5s")
        search = search.source(
            [
                "id",
                "title",
                "renderable_text",
                "authors",
                "created_date",
                "hubs",
                "slug",
                "score",
                "hot_score_v2",
                "unified_document_id",
                "document_type",
            ]
        )

        try:
            response = search.execute()
        except Exception as e:
            handle_search_error(e, query, offset, limit, sort)
            return {"results": [], "count": 0}

        results = self._process_document_results(response)

        return {
            "results": results,
            "count": response.hits.total.value,
        }

    def _apply_highlighting(self, search: Search) -> Search:
        highlight_fields = {
            "title": {"number_of_fragments": 0},
            "renderable_text": {"fragment_size": 700, "number_of_fragments": 1},
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
        if sort == self.SORT_NEWEST:
            search = search.sort(
                "-created_date",
                {"_score": {"order": "desc"}},
            )
        else:  # SORT_RELEVANCE or default
            search = search.sort({"_score": {"order": "desc"}})

        return search

    def _extract_document_highlights(self, highlights) -> tuple[str | None, str | None]:
        if not highlights:
            return None, None
        if hasattr(highlights, "title"):
            return highlights.title[0], "title"
        if hasattr(highlights, "renderable_text"):
            return highlights.renderable_text[0], "content"

        return None, None

    def _build_post_fields(self, hit) -> dict[str, Any]:
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
            highlights = getattr(hit.meta, "highlight", None)
            snippet, matched_field = self._extract_document_highlights(highlights)
            result = {
                "id": hit.id,
                "type": "post",
                "title": getattr(hit, "title", ""),
                "snippet": snippet,
                "matched_field": matched_field,
                "created_date": getattr(hit, "created_date", None),
                "score": getattr(hit, "score", 0),
                "hot_score_v2": getattr(hit, "hot_score_v2", 0),
                "_search_score": hit.meta.score,
            }
            result.update(self._build_post_fields(hit))
            result["hubs"] = self._process_hubs(hit)
            results.append(result)

        return results

    def _build_page_url(
        self, request, query: str, page: int, page_size: int, sort: str
    ) -> str:
        from urllib.parse import urlencode

        params = {"q": query, "page": page, "page_size": page_size, "sort": sort}
        base_url = request.build_absolute_uri(request.path)
        return f"{base_url}?{urlencode(params)}"
