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
                "source": "researchhub",
                "_score": result.get("_score", 1.0),  # Ensure _score is always set
            },
        },
        "user": {
            "document": UserDocument,
            "transform": lambda self, result: {
                "entity_type": "user",
                "id": result.get("_source", {}).get("id"),
                "display_name": result.get("_source", {}).get("full_name", ""),
                "source": "researchhub",
                "author_profile": result.get("_source", {}).get("author_profile", {}),
                "_score": result.get("_score", 1.0),  # Ensure _score is always set
            },
        },
        "post": {
            "document": PostDocument,
            "transform": lambda self, result: {
                "entity_type": "post",
                "id": result.get("_source", {}).get("id"),
                "display_name": result.get("_source", {}).get("title", ""),
                "document_type": result.get("_source", {}).get("document_type"),
                "authors": result.get("_source", {}).get("authors", []),
                "source": "researchhub",
                "_score": result.get("_score", 1.0),  # Ensure _score is always set
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
                "source": "researchhub",
                "_score": result.get("_score", 1.0),  # Ensure _score is always set
            },
        },
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
            "source": "openalex",
            "openalex_id": result.get("id"),  # OpenAlex ID from result
        }

    def transform_es_result(self, result):
        source = result.get("_source", {})
        normalized_doi = DOI.normalize_doi(source.get("doi"))
        return {
            "entity_type": "paper",
            "id": source.get("id"),  # ResearchHub paper ID
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
            "source": "researchhub",
            "openalex_id": source.get("openalex_id"),  # OpenAlex ID if exists in ES
            "_score": result.get("_score", 1.0),  # Ensure score is never zero/None
        }

    def get(self, request):
        """
        Combined autocomplete search using both OpenAlex and local Elasticsearch.
        Query params:
        - q: search query (required)
        - index: index(es) to search in (optional, defaults to 'paper')
                Can be a single index or comma-separated list (e.g. 'user,person')
        - limit: maximum number of results to return (optional, defaults to 10)
        - balanced: whether to return balanced results across entity types (optional, defaults to false)
        """
        query = request.query_params.get("q", None)
        if not query:
            return Response(
                {"error": "Search query is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

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

        # Check if balanced results are requested
        balanced = request.query_params.get("balanced", "false").lower() == "true"

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
                            if result.get(
                                "external_id"
                            )  # Only include results with external_id (DOI)
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

                    suggest = search.suggest(
                        "suggestions", query, completion={"field": suggest_field}
                    )
                    es_response = suggest.execute().suggest.to_dict()
                    es_results = []
                    for suggestion in es_response.get("suggestions", []):
                        options = suggestion.get("options", [])
                        es_results.extend(
                            [transform_func(self, option) for option in options[:3]]
                        )
                    results.extend(es_results)

                # Handle paper-specific deduplication
                if index == "paper":
                    unique_results = []

                    # First add ResearchHub results
                    for result in sorted(
                        [r for r in results if r["source"] == "researchhub"],
                        key=lambda x: x.get("_score", 0),
                        reverse=True,
                    ):
                        doi = result.get("normalized_doi")
                        if doi and doi not in seen_dois:
                            seen_dois.add(doi)
                            del result["normalized_doi"]
                            unique_results.append(result)

                    # Then add OpenAlex results if DOI not already seen
                    for result in sorted(
                        [r for r in results if r["source"] == "openalex"],
                        key=lambda x: x.get("_score", 0),
                        reverse=True,
                    ):
                        doi = result.get("normalized_doi")
                        if doi and doi not in seen_dois:
                            seen_dois.add(doi)
                            del result["normalized_doi"]
                            unique_results.append(result)

                    # Store sorted paper results
                    entity_type = "paper"
                    results_by_type[entity_type] = sorted(
                        unique_results, key=lambda x: x.get("_score", 0), reverse=True
                    )
                else:
                    # For other indexes, sort by score and add to corresponding type
                    sorted_results = sorted(
                        results, key=lambda x: x.get("_score", 0), reverse=True
                    )

                    # Determine entity type based on the first result (if any)
                    if sorted_results:
                        entity_type = sorted_results[0].get("entity_type", index)
                        # Add to results by type
                        results_by_type[entity_type] = sorted_results

            # Apply entity type weights to scores
            for entity_type, results in results_by_type.items():
                # Apply default weight based on entity type
                weight = self.DEFAULT_WEIGHTS.get(entity_type, 1.0)

                # Special handling for users/persons - boost exact matches
                if entity_type in ["user", "person"] and query:
                    for result in results:
                        # Get user's display name
                        display_name = result.get("display_name", "")

                        # Apply exact match boosting - give extra weight for exact matches
                        original_score = result.get("_score", 1.0)

                        # Check for exact match (ignoring case) and boost substantially
                        if display_name.lower() == query.lower():
                            # Apply exact match multiplier (5x)
                            exact_match_bonus = 5.0
                            result["_score"] = (
                                original_score * weight * exact_match_bonus
                            )
                            result["_boost"] = "exact_name_match"
                        # Check for name contains query or query contains name
                        elif (
                            query.lower() in display_name.lower()
                            or display_name.lower() in query.lower()
                        ):
                            # Apply partial match multiplier (2x)
                            partial_match_bonus = 2.0
                            result["_score"] = (
                                original_score * weight * partial_match_bonus
                            )
                            result["_boost"] = "partial_name_match"
                        else:
                            # Standard weight
                            result["_score"] = original_score * weight
                            result["_original_score"] = original_score
                else:
                    # Standard entity weighting for non-user types
                    for result in results:
                        original_score = result.get("_score", 1.0)
                        result["_original_score"] = original_score
                        result["_score"] = original_score * weight

            # Combine results based on strategy (balanced or not)
            all_results = []

            if balanced and len(results_by_type) > 1:
                # Calculate quota for each type
                entity_types = list(results_by_type.keys())
                min_per_type = 2  # Minimum results per type if available
                remaining_slots = limit - (min_per_type * len(entity_types))

                # First, add minimum quota for each type
                for entity_type in entity_types:
                    type_results = results_by_type[entity_type]
                    quota = min(min_per_type, len(type_results))
                    all_results.extend(type_results[:quota])
                    # Remove used results
                    results_by_type[entity_type] = type_results[quota:]

                # Distribute remaining slots based on weighted scores
                if remaining_slots > 0 and any(
                    len(results) > 0 for results in results_by_type.values()
                ):
                    # Create merged list of remaining results
                    remaining_results = []
                    for entity_type, results in results_by_type.items():
                        for result in results:
                            remaining_results.append(result)

                    # Sort by weighted score and add top results
                    sorted_remaining = sorted(
                        remaining_results,
                        key=lambda x: x.get("_score", 0),
                        reverse=True,
                    )
                    all_results.extend(sorted_remaining[:remaining_slots])
            else:
                # Just combine all results and sort by weighted score
                for results in results_by_type.values():
                    all_results.extend(results)

            # Sort combined results by weighted score
            all_results = sorted(
                all_results, key=lambda x: x.get("_score", 0), reverse=True
            )

            # Apply limit
            all_results = all_results[:limit]

            return Response(all_results, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
