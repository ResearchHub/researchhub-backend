"""
Unified search service for searching across documents (papers/posts)
and people (authors/users).
"""

import logging
from typing import Any

from opensearchpy import Q, Search

from search.documents.paper import PaperDocument
from search.documents.person import PersonDocument
from search.documents.post import PostDocument
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
        self.person_index = PersonDocument._index._name
        self.query_builder = UnifiedSearchQueryBuilder()

    def search(
        self,
        query: str,
        page: int = 1,
        page_size: int = 10,
        sort: str = SORT_RELEVANCE,
        request=None,
    ) -> dict[str, Any]:

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
                    return {
                        "count": doi_result["count"],
                        "next": None,
                        "previous": None,
                        "documents": doi_result["results"],
                        "people": [],
                        "aggregations": {},
                    }
        except Exception:
            # Fallback to regular flow if DOI parsing/search fails
            pass

        # Search documents (papers and posts)
        document_results = self._search_documents(query, offset, page_size, sort)

        # Search people (authors/users)
        people_results = self._search_people(query, offset, page_size, sort)

        # Combine results
        total_count = document_results["count"] + people_results["count"]

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

        return {
            "count": total_count,
            "next": next_url,
            "previous": previous_url,
            "documents": document_results["results"],
            "people": people_results["results"],
            "aggregations": document_results["aggregations"],
        }

    def _search_documents(
        self, query: str, offset: int, limit: int, sort: str
    ) -> dict[str, Any]:

        # Create multi-index search for papers and posts
        search = Search(index=[self.paper_index, self.post_index])

        # Build query with field boosting
        query_obj = self.query_builder.build_document_query(query)
        search = search.query(query_obj)

        # Light rescore to reward author+title co-occurrence in top results
        try:
            rescore_block = self.query_builder.build_rescore_query(query)
            search = search.extra(rescore=[rescore_block])
        except Exception:
            # If the backend version doesn't support rescore, ignore gracefully
            pass

        # Apply highlighting
        search = self._apply_highlighting(search, is_document=True)

        # Add aggregations
        search = self._add_aggregations(search)

        # Apply sorting
        search = self._apply_sort(search, sort)

        # Apply pagination
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
                "unified_document_id",
                "document_type",
            ]
        )

        # Execute search
        try:
            response = search.execute()
        except Exception as e:
            logger.error(f"Document search failed: {str(e)}")
            return {"results": [], "count": 0, "aggregations": {}}

        # Process results
        results = self._process_document_results(response)

        # Process aggregations
        aggregations = self._process_aggregations(response)

        return {
            "results": results,
            "count": response.hits.total.value,
            "aggregations": aggregations,
        }

    def _search_people(
        self, query: str, offset: int, limit: int, sort: str
    ) -> dict[str, Any]:
        # Create search for people
        search = Search(index=self.person_index)

        # Build query
        query_obj = self.query_builder.build_person_query(query)
        search = search.query(query_obj)

        # Apply highlighting
        search = self._apply_highlighting(search, is_document=False)

        # Apply sorting (simplified for people)
        if sort == self.SORT_NEWEST:
            search = search.sort("-created_date", {"_score": {"order": "desc"}})
        else:
            # For people, default to relevance or reputation-based scoring
            search = search.sort({"_score": {"order": "desc"}})

        # Apply pagination
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
                "first_name",
                "last_name",
                "full_name",
                "profile_image",
                "headline",
                "description",
                "institutions",
                "user_reputation",
                "user_id",
            ]
        )

        # Execute search
        try:
            response = search.execute()
        except Exception as e:
            logger.error(f"People search failed: {str(e)}")
            return {"results": [], "count": 0}

        # Process results
        results = self._process_people_results(response)

        return {
            "results": results,
            "count": response.hits.total.value,
        }

    def _search_documents_by_doi(self, normalized_doi: str) -> dict[str, Any]:

        search = Search(index=[self.paper_index, self.post_index])
        search = search.query(Q("term", doi={"value": normalized_doi}))

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

    def _apply_highlighting(self, search: Search, is_document: bool = True) -> Search:
        """
        Apply highlighting configuration to search.
        """
        if is_document:
            highlight_fields = {
                "paper_title": {"number_of_fragments": 0},
                "title": {"number_of_fragments": 0},
                "abstract": {"fragment_size": 200, "number_of_fragments": 1},
                "renderable_text": {"fragment_size": 200, "number_of_fragments": 1},
                "raw_authors.full_name": {"number_of_fragments": 0},
                "authors.full_name": {"number_of_fragments": 0},
            }
        else:
            highlight_fields = {
                "full_name": {"number_of_fragments": 0},
                "description": {"fragment_size": 200, "number_of_fragments": 1},
                "headline.title": {"fragment_size": 150, "number_of_fragments": 1},
            }

        search = search.highlight_options(
            pre_tags=["<mark>"],
            post_tags=["</mark>"],
        )

        for field, options in highlight_fields.items():
            search = search.highlight(field, **options)

        return search

    def _add_aggregations(self, search: Search) -> Search:

        # Year aggregation (from created_date or paper_publish_date)
        search.aggs.bucket(
            "years",
            "date_histogram",
            field="created_date",
            calendar_interval="year",
            format="yyyy",
        )

        # Content type aggregation (from index name)
        search.aggs.bucket(
            "content_types",
            "terms",
            field="_index",
            size=10,
        )

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

    def _process_document_results(self, response) -> list[dict[str, Any]]:

        results = []

        for hit in response.hits:
            # Determine document type from index
            doc_type = "paper" if "paper" in hit.meta.index else "post"

            # Get highlights
            highlights = getattr(hit.meta, "highlight", None)
            snippet = None
            matched_field = None

            if highlights:
                # Priority: title > abstract/content
                if hasattr(highlights, "paper_title"):
                    snippet = highlights.paper_title[0]
                    matched_field = "title"
                elif hasattr(highlights, "title"):
                    snippet = highlights.title[0]
                    matched_field = "title"
                elif hasattr(highlights, "abstract"):
                    snippet = highlights.abstract[0]
                    matched_field = "abstract"
                elif hasattr(highlights, "renderable_text"):
                    snippet = highlights.renderable_text[0]
                    matched_field = "content"

            # Build result object
            result = {
                "id": hit.id,
                "type": doc_type,
                "title": getattr(hit, "paper_title", None) or getattr(hit, "title", ""),
                "snippet": snippet,
                "matched_field": matched_field,
                "created_date": getattr(hit, "created_date", None),
                "score": getattr(hit, "score", 0),
                "_search_score": hit.meta.score,
            }

            # Add paper-specific fields
            if doc_type == "paper":
                raw_doi = getattr(hit, "doi", None)
                result.update(
                    {
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
                        "unified_document_id": getattr(
                            hit, "unified_document_id", None
                        ),
                    }
                )
            else:  # post
                result.update(
                    {
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
                        "unified_document_id": getattr(
                            hit, "unified_document_id", None
                        ),
                    }
                )

            # Add hubs
            hubs = getattr(hit, "hubs", [])
            if hubs:
                result["hubs"] = [
                    {
                        "id": hub.get("id"),
                        "name": hub.get("name"),
                        "slug": hub.get("slug"),
                    }
                    for hub in hubs
                ]
            else:
                result["hubs"] = []

            results.append(result)

        return results

    def _process_people_results(self, response) -> list[dict[str, Any]]:
        results = []

        for hit in response.hits:
            # Get highlights
            highlights = getattr(hit.meta, "highlight", None)
            snippet = None
            matched_field = None

            if highlights:
                # Priority: name > headline > description
                if hasattr(highlights, "full_name"):
                    snippet = highlights.full_name[0]
                    matched_field = "name"
                elif hasattr(highlights, "headline"):
                    snippet = highlights.headline[0]
                    matched_field = "headline"
                elif hasattr(highlights, "description"):
                    snippet = highlights.description[0]
                    matched_field = "description"

            # Build result object
            result = {
                "id": hit.id,
                "full_name": getattr(hit, "full_name", ""),
                "profile_image": getattr(hit, "profile_image", None),
                "snippet": snippet,
                "matched_field": matched_field,
                "user_reputation": getattr(hit, "user_reputation", 0),
                "user_id": getattr(hit, "user_id", None),
                "_search_score": hit.meta.score,
            }

            # Add headline
            headline = getattr(hit, "headline", None)
            if headline:
                if hasattr(headline, "to_dict"):
                    result["headline"] = headline.to_dict()
                else:
                    result["headline"] = headline

            # Add institutions
            institutions = getattr(hit, "institutions", [])
            if institutions:
                result["institutions"] = [
                    {"id": inst.get("id"), "name": inst.get("name")}
                    for inst in institutions
                ]
            else:
                result["institutions"] = []

            results.append(result)

        return results

    def _process_aggregations(self, response) -> dict[str, Any]:

        aggregations = {}

        if hasattr(response, "aggregations"):
            aggs = response.aggregations

            # Process year aggregation
            if hasattr(aggs, "years"):
                aggregations["years"] = [
                    {"key": bucket.key_as_string, "doc_count": bucket.doc_count}
                    for bucket in aggs.years.buckets
                ]

            # Process content type aggregation
            if hasattr(aggs, "content_types"):
                # Map index names to friendly names
                type_mapping = {
                    "paper": "paper",
                    "post": "post",
                }
                aggregations["content_types"] = []
                for bucket in aggs.content_types.buckets:
                    index_name = bucket.key
                    for key, value in type_mapping.items():
                        if key in index_name:
                            aggregations["content_types"].append(
                                {"key": value, "doc_count": bucket.doc_count}
                            )
                            break

        return aggregations

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
