import logging
import time
from typing import Any

from opensearchpy import Q, Search
from opensearchpy.helpers.utils import AttrDict, AttrList

from search.base.utils import seconds_to_milliseconds
from search.documents.paper import PaperDocument
from search.documents.post import PostDocument
from search.services.search_error_utils import handle_search_error
from search.services.unified_search_query_builder import (
    PopularityConfig,
    UnifiedSearchQueryBuilder,
)
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

        if sort not in self.VALID_SORT_OPTIONS:
            sort = self.SORT_RELEVANCE

        offset = (page - 1) * page_size

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
            pass

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
        search = Search(index=[self.paper_index, self.post_index])
        config = popularity_config or self.query_builder.popularity_config
        query_obj = self.query_builder.build_document_query_with_popularity(
            query, config
        )
        author_filter = self._build_author_filter()
        filtered_query = Q("bool", must=[query_obj], filter=[author_filter])
        search = search.query(filtered_query)

        search = self._apply_highlighting(search)

        search = self._apply_sort(search, sort)

        search = search[offset:offset + limit]

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
                "hot_score_v2",
                "unified_document_id",
                "document_type",
                "external_source",
            ]
        )

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
        if response.hits.total.value > 0:
            first_hit_index = response.hits[0].meta.index if response.hits else "N/A"
            logger.info(f"First hit index: {first_hit_index}")

    def _search_documents_by_doi(self, normalized_doi: str) -> dict[str, Any]:
        search = Search(index=[self.paper_index, self.post_index])
        doi_query = Q("term", doi={"value": normalized_doi})
        author_filter = self._build_author_filter()
        filtered_query = Q("bool", must=[doi_query], filter=[author_filter])
        search = search.query(filtered_query)
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
                "hot_score_v2",
                "unified_document_id",
                "document_type",
                "external_source",
            ]
        )
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
            "journal": self._extract_journal_from_hubs(hit),
        }

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

    def _extract_journal_from_hubs(self, hit) -> str | None:
        """Extract journal name from hubs where namespace='journal'."""
        try:
            hubs = getattr(hit, "hubs", None)
            if not hubs:
                logger.debug(f"No hubs found for hit {getattr(hit, 'id', 'unknown')}")
                return None

            # Convert AttrList or other iterables to list
            if isinstance(hubs, (list, tuple, AttrList)):
                hubs = list(hubs)
            else:
                logger.debug(
                    f"Expected hubs to be list/tuple/AttrList, "
                    f"got {type(hubs).__name__} for hit {getattr(hit, 'id', 'unknown')}"
                )
                return None

            logger.debug(
                f"Hit {getattr(hit, 'id', 'unknown')}: Processing {len(hubs)} hubs "
                f"for journal extraction"
            )

            for hub in hubs:
                try:
                    # Handle dict, AttrDict, or object with attributes
                    if isinstance(hub, dict):
                        namespace = hub.get("namespace")
                        name = hub.get("name")
                    elif isinstance(hub, AttrDict):
                        # AttrDict supports dictionary-style access with []
                        try:
                            namespace = hub.get("namespace", None)
                            name = hub.get("name", None)
                            # If .get() doesn't work, try direct access
                            if namespace is None:
                                try:
                                    namespace = hub["namespace"]
                                except (KeyError, TypeError):
                                    pass
                            if name is None:
                                try:
                                    name = hub["name"]
                                except (KeyError, TypeError):
                                    pass
                        except (KeyError, TypeError, AttributeError):
                            continue
                    else:
                        namespace = getattr(hub, "namespace", None)
                        name = getattr(hub, "name", None)

                    logger.debug(
                        f"Hit {getattr(hit, 'id', 'unknown')}: "
                        f"Hub namespace={repr(namespace)}, "
                        f"name={repr(name)}, comparing to 'journal'"
                    )

                    if namespace == "journal":
                        if isinstance(name, str) and name.strip():
                            logger.debug(
                                f"Found journal for hit "
                                f"{getattr(hit, 'id', 'unknown')}: {name}"
                            )
                            return name.strip()
                except Exception as hub_error:
                    logger.debug(
                        f"Error processing hub in journal extraction: "
                        f"{hub_error}"
                    )
                    continue

            logger.debug(
                f"No journal hub found for hit {getattr(hit, 'id', 'unknown')}"
            )
            return None
        except Exception as e:
            logger.warning(f"Failed to extract journal from hubs: {e}", exc_info=True)
            return None

    def _process_hubs(self, hit) -> list[dict[str, Any]]:
        """Process and format hubs from a search hit with defensive handling."""
        try:
            hubs = getattr(hit, "hubs", None)
            if not hubs:
                return []

            # Convert AttrList or other iterables to list
            if isinstance(hubs, (list, tuple, AttrList)):
                hubs = list(hubs)
            else:
                logger.warning(
                    f"Expected hubs to be list/tuple/AttrList, "
                    f"got {type(hubs).__name__} for hit {getattr(hit, 'id', 'unknown')}"
                )
                return []

            result = []
            for hub in hubs:
                try:
                    # Handle dict, AttrDict, or object with attributes
                    if isinstance(hub, dict):
                        hub_id = hub.get("id")
                        hub_name = hub.get("name")
                        hub_slug = hub.get("slug")
                        hub_namespace = hub.get("namespace")
                    elif isinstance(hub, AttrDict):
                        # AttrDict supports dictionary-style access with []
                        try:
                            hub_id = hub["id"] if "id" in hub else None
                            hub_name = hub["name"] if "name" in hub else None
                            hub_slug = hub["slug"] if "slug" in hub else None
                            hub_namespace = (
                                hub["namespace"] if "namespace" in hub else None
                            )
                        except (KeyError, TypeError):
                            continue
                    else:
                        hub_id = getattr(hub, "id", None)
                        hub_name = getattr(hub, "name", None)
                        hub_slug = getattr(hub, "slug", None)
                        hub_namespace = getattr(hub, "namespace", None)

                    # Include hub if it has an id or a valid name
                    if hub_id is not None or (hub_name and isinstance(hub_name, str)):
                        result.append(
                            {
                                "id": hub_id,
                                "name": hub_name if isinstance(hub_name, str) else None,
                                "slug": hub_slug if isinstance(hub_slug, str) else None,
                                "namespace": (
                                    hub_namespace
                                    if isinstance(hub_namespace, str)
                                    else None
                                ),
                            }
                        )
                except Exception as hub_error:
                    logger.warning(
                        f"Failed to process individual hub: {hub_error}, hub: {hub}"
                    )
                    continue

            return result
        except Exception as e:
            logger.warning(f"Failed to process hubs: {e}", exc_info=True)
            return []

    def _process_document_results(self, response) -> list[dict[str, Any]]:
        results = []
        for hit in response.hits:
            doc_type = "paper" if "paper" in hit.meta.index else "post"
            highlights = getattr(hit.meta, "highlight", None)
            snippet, matched_field = self._extract_document_highlights(highlights)
            result = {
                "id": hit.id,
                "type": doc_type,
                "title": getattr(hit, "paper_title", None) or getattr(hit, "title", ""),
                "snippet": snippet,
                "matched_field": matched_field,
                "created_date": getattr(hit, "created_date", None),
                "score": getattr(hit, "score", 0),
                "hot_score_v2": getattr(hit, "hot_score_v2", 0),
                "_search_score": hit.meta.score,
            }
            if doc_type == "paper":
                result.update(self._build_paper_fields(hit))
            else:
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
