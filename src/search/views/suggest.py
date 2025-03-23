from elasticsearch_dsl import Search
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from search.documents.paper import PaperDocument
from search.documents.person import PersonDocument
from search.documents.post import PostDocument
from search.documents.user import UserDocument
from utils.doi import DOI
from utils.openalex import OpenAlex


class SuggestView(APIView):
    permission_classes = [AllowAny]
    renderer_classes = [JSONRenderer]

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
            "_score": result.get("_score"),  # Add _score property to each result
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
            all_results = []
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
                        es_results.extend(
                            [
                                transform_func(self, option)
                                for option in suggestion.get("options", [])[:3]
                            ]
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

                    all_results.extend(unique_results)
                else:
                    # For other indexes, just sort by score and add all results
                    all_results.extend(
                        sorted(results, key=lambda x: x.get("_score", 0), reverse=True)
                    )

            # Limit the number of results returned
            all_results = all_results[:limit]

            return Response(all_results, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
