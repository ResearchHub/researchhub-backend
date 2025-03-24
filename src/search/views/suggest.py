import logging

from elasticsearch_dsl import Search
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from search.documents.hub import HubDocument
from search.documents.paper import PaperDocument
from search.documents.person import PersonDocument
from search.documents.post import PostDocument
from search.documents.user import UserDocument
from utils.doi import DOI
from utils.openalex import OpenAlex

logger = logging.getLogger(__name__)


class SuggestView(APIView):
    permission_classes = [AllowAny]
    renderer_classes = [JSONRenderer]

    # Default entity type weights to ensure fair representation
    DEFAULT_WEIGHTS = {
        "hub": 3.0,  # Prioritize hubs (communities)
        "paper": 2.0,  # Then papers
        "user": 2.5,  # Increased weight for users
        "person": 2.5,  # Authors same as users
        "post": 1.0,  # Regular posts
    }

    # Map of index names to their document classes and transform functions
    INDEX_MAP = {
        "paper": {
            "document": PaperDocument,
            "transform": lambda self, result: self.transform_es_result(result),
            "external_search": True,  # Indicates if OpenAlex search should be included
        },
        "author": {
            "document": PersonDocument,
            "transform": lambda self, result: {
                "entity_type": "person",
                "id": result.get("_source", {}).get("id"),
                "display_name": result.get("_source", {}).get("full_name", ""),
                "profile_image": result.get("_source", {}).get("profile_image"),
                "headline": result.get("_source", {}).get("headline", {}),
                "created_date": result.get("_source", {}).get("created_date"),
                "source": "researchhub",
                "_score": result.get("_score", 1.0),
            },
        },
        "user": {
            "document": UserDocument,
            "transform": lambda self, result: {
                "entity_type": "user",
                "id": result.get("_source", {}).get("id"),
                "display_name": result.get("_source", {}).get("full_name", ""),
                "created_date": result.get("_source", {}).get("created_date"),
                "source": "researchhub",
                "author_profile": result.get("_source", {}).get("author_profile", {}),
                "_score": result.get("_score", 1.0),
            },
        },
        "post": {
            "document": PostDocument,
            "transform": lambda self, result: {
                "entity_type": "post",
                "id": result.get("_source", {}).get("id"),
                "display_name": result.get("_source", {}).get("title", ""),
                "document_type": result.get("_source", {}).get("document_type"),
                "created_date": result.get("_source", {}).get("created_date"),
                "authors": result.get("_source", {}).get("authors", []),
                "source": "researchhub",
                "_score": result.get("_score", 1.0),
            },
        },
        "hub": {
            "document": HubDocument,
            "transform": lambda self, result: {
                "entity_type": "hub",
                "id": result.get("_source", {}).get("id"),
                "display_name": result.get("_source", {}).get("name", ""),
                "slug": result.get("_source", {}).get("slug"),
                "description": result.get("_source", {}).get("description", ""),
                "paper_count": result.get("_source", {}).get("paper_count", 0),
                "discussion_count": result.get("_source", {}).get(
                    "discussion_count", 0
                ),
                "created_date": result.get("_source", {}).get("created_date"),
                "source": "researchhub",
                "_score": result.get("_score", 1.0),
            },
        },
    }

    def safe_transform(self, transform_func, result, default_entity_type=None):
        """Safely apply a transform function with error handling"""
        try:
            return transform_func(self, result)
        except Exception as e:
            logger.error(f"Error transforming result: {str(e)}")

            # Return a minimal valid result with default values
            return {
                "entity_type": default_entity_type or "unknown",
                "id": (
                    result.get("_source", {}).get("id")
                    if isinstance(result, dict)
                    else None
                ),
                "display_name": "Error processing result",
                "source": "researchhub",
                "_score": 0.1,  # Low default score
            }

    def transform_openalex_result(self, result):
        normalized_doi = DOI.normalize_doi(result.get("external_id"))
        return {
            "entity_type": "paper",
            "doi": (f"{normalized_doi}" if normalized_doi else None),
            "normalized_doi": normalized_doi,  # Used for comparison
            "display_name": result.get("display_name", ""),
            "authors": (
                result.get("hint", "").split(", ") if result.get("hint") else []
            ),
            "citations": result.get("cited_by_count", 0),
            "created_date": result.get("publication_date"),
            "source": "openalex",
            "openalex_id": result.get("id"),
        }

    def transform_es_result(self, result):
        source = result.get("_source", {})
        normalized_doi = DOI.normalize_doi(source.get("doi"))
        return {
            "entity_type": "paper",
            "id": source.get("id"),
            "doi": (f"{normalized_doi}" if normalized_doi else None),
            "normalized_doi": normalized_doi,  # Used for comparison
            "display_name": source.get("paper_title", ""),
            "authors": [
                author.get("full_name", "")
                for author in source.get("raw_authors", [])
                if author.get("full_name")
            ],
            "citations": source.get("citations", 0),
            "date_published": source.get("paper_publish_date"),
            "created_date": source.get("created_date"),
            "source": "researchhub",
            "openalex_id": source.get("openalex_id"),
            "_score": result.get("_score", 1.0),
        }

    def get(self, request):
        """
        Combined autocomplete search using both OpenAlex and local Elasticsearch.
        Query params:
        - q: search query (required)
        - index: index(es) to search in (optional, defaults to 'paper')
               Can be a single index or comma-separated list (e.g. 'user,person')
        - limit: maximum number of results to return (optional, defaults to 10)
        """
        query = request.query_params.get("q", None)
        # More strict validation for empty query strings
        if not query or query.strip() == "":
            return Response(
                {"error": "Search query is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Special handling for DOI inputs
        if DOI.is_doi(query):
            logger.info(f"DOI detected in query: {query}")
            return self.handle_doi_search(query, request)

        # Parse indexes from the query parameter
        index_param = request.query_params.get("index", "paper")
        indexes = [idx.strip() for idx in index_param.split(",")]

        # Get limit parameter (default to 10)
        try:
            limit = int(request.query_params.get("limit", 10))
            if limit < 1:
                limit = 10  # Minimum of 1 result
        except ValueError:
            limit = 10  # Default if invalid value

        # Validate all indexes
        invalid_indexes = [idx for idx in indexes if idx not in self.INDEX_MAP]
        if invalid_indexes:
            available_indexes = ", ".join(self.INDEX_MAP.keys())
            return Response(
                {
                    "error": (
                        f"Invalid indexes: {', '.join(invalid_indexes)}. "
                        f"Available indexes: {available_indexes}"
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            results = self.perform_regular_search(query, indexes, limit)
            return Response(results, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error in search: {str(e)}")
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def handle_doi_search(self, doi_query, request):
        """
        Handle search specifically for DOI inputs by searching only for exact matches
        across papers and posts.
        """
        try:
            # Get limit parameter
            try:
                limit = int(request.query_params.get("limit", 10))
                if limit < 1:
                    limit = 10
            except ValueError:
                limit = 10

            # Generate all DOI variants to search for
            doi_variants = DOI.get_variants(doi_query)
            if not doi_variants:
                return Response([], status=status.HTTP_200_OK)

            results = []
            seen_dois = set()

            # 1. Search in papers index
            paper_document = self.INDEX_MAP["paper"]["document"]
            paper_search = Search(index=paper_document._index._name)

            # Create a combined query for all DOI variants
            should_queries = []
            for variant in doi_variants:
                should_queries.append({"term": {"doi.keyword": variant}})
                should_queries.append({"match_phrase": {"doi": variant}})

            paper_query = {
                "bool": {"should": should_queries, "minimum_should_match": 1}
            }
            paper_search = paper_search.query(paper_query)
            paper_response = paper_search.execute()

            # Process Elasticsearch paper results
            if hasattr(paper_response, "hits") and paper_response.hits:
                for hit in paper_response.hits:
                    result = self.transform_es_result(hit.to_dict())
                    normalized_doi = result.get("normalized_doi")
                    if normalized_doi and normalized_doi not in seen_dois:
                        seen_dois.add(normalized_doi)
                        if "normalized_doi" in result:
                            del result["normalized_doi"]
                        results.append(result)

            # 2. Get OpenAlex results for the DOI
            openalex = OpenAlex()
            openalex_response = openalex.autocomplete_works(doi_query)
            for oa_result in openalex_response.get("results", []):
                if not oa_result.get("external_id"):
                    continue

                result = self.transform_openalex_result(oa_result)
                normalized_doi = result.get("normalized_doi")
                if normalized_doi and normalized_doi not in seen_dois:
                    seen_dois.add(normalized_doi)
                    if "normalized_doi" in result:
                        del result["normalized_doi"]
                    results.append(result)

            # 3. Search in posts index (if posts could have DOIs)
            post_document = self.INDEX_MAP["post"]["document"]
            post_search = Search(index=post_document._index._name)

            # Create query for posts with the DOI in content
            post_should_queries = []
            for variant in doi_variants:
                post_should_queries.append({"match_phrase": {"content": variant}})
                post_should_queries.append({"match_phrase": {"title": variant}})

            post_query = {
                "bool": {"should": post_should_queries, "minimum_should_match": 1}
            }
            post_search = post_search.query(post_query)
            post_response = post_search.execute()

            # Process post results
            transform_func = self.INDEX_MAP["post"]["transform"]
            if hasattr(post_response, "hits") and post_response.hits:
                for hit in post_response.hits:
                    result = self.safe_transform(transform_func, hit.to_dict(), "post")
                    results.append(result)

            # Sort by relevance (exact DOI matches first)
            # Give higher scores to results with exact DOI match
            for result in results:
                if result.get("entity_type") == "paper":
                    doi_value = result.get("doi", "")
                    has_doi_match = False
                    for variant in doi_variants:
                        if variant in doi_value:
                            has_doi_match = True
                            break

                    if doi_value and has_doi_match:
                        result["_score"] = 1000  # Very high score for exact DOI match

            results = sorted(results, key=lambda x: x.get("_score", 0), reverse=True)[
                :limit
            ]

            # If we found no results, fall back to regular search
            if not results:
                msg = f"No direct DOI matches found for {doi_query}"
                msg += ", falling back to regular search"
                logger.info(msg)
                # Parse indexes for fallback
                index_param = request.query_params.get("index", "paper")
                indexes = [idx.strip() for idx in index_param.split(",")]

                # Validate indexes
                invalid_indexes = [idx for idx in indexes if idx not in self.INDEX_MAP]
                if invalid_indexes:
                    available_indexes = ", ".join(self.INDEX_MAP.keys())
                    return Response(
                        {
                            "error": (
                                f"Invalid indexes: {', '.join(invalid_indexes)}. "
                                f"Available indexes: {available_indexes}"
                            )
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                # Perform regular search as fallback
                fallback_results = self.perform_regular_search(
                    doi_query, indexes, limit
                )
                return Response(fallback_results, status=status.HTTP_200_OK)

            return Response(results, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error in DOI search: {str(e)}")
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def perform_regular_search(self, query, indexes, limit):
        """
        Perform the regular search functionality extracted from the get method.
        This allows us to reuse this logic for fallback when DOI search finds
        no results.
        """
        # Results by entity type
        results_by_type = {}
        seen_dois = set()  # For deduplicating paper results

        # Process each index
        for index in indexes:
            results = []
            index_config = self.INDEX_MAP[index]
            document = index_config["document"]
            transform_func = index_config["transform"]

            # Get OpenAlex results if enabled for this index
            if index_config.get("external_search", False):
                openalex = OpenAlex()
                openalex_response = openalex.autocomplete_works(query)
                results.extend(
                    [
                        self.transform_openalex_result(result)
                        for result in openalex_response.get("results", [])
                        if result.get("external_id")  # Only include results with DOI
                    ]
                )

            # Get local Elasticsearch results
            search = Search(index=document._index._name)
            if hasattr(document, "_doc_type"):
                suggest_field = "suggestion_phrases"
                if index == "user":
                    suggest_field = "full_name_suggest"
                elif index in ["hub", "journal"]:
                    suggest_field = "name_suggest"

                try:
                    suggest = search.suggest(
                        "suggestions", query, completion={"field": suggest_field}
                    )
                    response = suggest.execute()

                    # For test mocks - handle direct list responses
                    if isinstance(response, list):
                        es_results = []
                        for option in response:
                            try:
                                transformed = self.safe_transform(
                                    transform_func, option, index
                                )
                                es_results.append(transformed)
                            except Exception as e:
                                logger.error(
                                    f"Error transforming option in mock list: "
                                    f"{str(e)}"
                                )
                        results.extend(es_results)
                    # Normal ES response with suggestion attribute
                    elif hasattr(response, "suggest") and response.suggest:
                        es_response = response.suggest.to_dict()
                        es_results = []
                        for suggestion in es_response.get("suggestions", []):
                            options = suggestion.get("options", [])
                            es_results.extend(
                                [
                                    self.safe_transform(transform_func, option, index)
                                    for option in options[:3]  # Top 3 per suggestion
                                ]
                            )
                        results.extend(es_results)
                except Exception as e:
                    logger.error(f"Error retrieving suggestions for {index}: {str(e)}")

            # Handle paper-specific deduplication
            if index == "paper":
                # Process ResearchHub results first
                rh_results = sorted(
                    [r for r in results if r["source"] == "researchhub"],
                    key=lambda x: x.get("_score", 0),
                    reverse=True,
                )

                # Then OpenAlex results
                oa_results = sorted(
                    [r for r in results if r["source"] == "openalex"],
                    key=lambda x: x.get("_score", 0),
                    reverse=True,
                )

                # Deduplicate and combine
                unique_results = []

                # Process RH results first (higher priority)
                for result in rh_results:
                    doi = result.get("normalized_doi")
                    if doi and doi not in seen_dois:
                        seen_dois.add(doi)
                        del result["normalized_doi"]
                        unique_results.append(result)

                # Then process OpenAlex results
                for result in oa_results:
                    doi = result.get("normalized_doi")
                    if doi and doi not in seen_dois:
                        seen_dois.add(doi)
                        del result["normalized_doi"]
                        unique_results.append(result)

                results_by_type["paper"] = unique_results
            else:
                # For other indexes, store by entity type
                sorted_results = sorted(
                    results, key=lambda x: x.get("_score", 0), reverse=True
                )

                if sorted_results:
                    entity_type = sorted_results[0].get("entity_type", index)
                    results_by_type[entity_type] = sorted_results

        # Apply entity type weights to scores
        for entity_type, results in results_by_type.items():
            weight = self.DEFAULT_WEIGHTS.get(entity_type, 1.0)

            # Special handling for users/persons - boost exact matches
            if entity_type in ["user", "person"] and query:
                for result in results:
                    display_name = result.get("display_name", "")
                    original_score = result.get("_score", 1.0)

                    # Exact match boosting
                    if display_name.lower() == query.lower():
                        exact_match_bonus = 5.0
                        result["_score"] = original_score * weight * exact_match_bonus
                        result["_boost"] = "exact_name_match"
                    # Partial match boosting
                    elif (
                        query.lower() in display_name.lower()
                        or display_name.lower() in query.lower()
                    ):
                        partial_match_bonus = 2.0
                        result["_score"] = original_score * weight * partial_match_bonus
                        result["_boost"] = "partial_name_match"
                    else:
                        # Standard weight
                        result["_score"] = original_score * weight
                        result["_original_score"] = original_score
            else:
                # Standard entity weighting
                for result in results:
                    original_score = result.get("_score", 1.0)
                    result["_original_score"] = original_score
                    result["_score"] = original_score * weight

        # Combine and sort results
        all_results = []
        for results in results_by_type.values():
            all_results.extend(results)

        all_results = sorted(
            all_results, key=lambda x: x.get("_score", 0), reverse=True
        )[:limit]

        return all_results
