from elasticsearch_dsl import Search
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from search.documents.paper import PaperDocument
from utils.doi import DOI
from utils.openalex import OpenAlex


class SuggestView(APIView):
    permission_classes = [AllowAny]
    renderer_classes = [JSONRenderer]

    def transform_openalex_result(self, result):
        normalized_doi = DOI.normalize_doi(result.get("external_id"))
        return {
            "entity_type": "work",
            "doi": (f"{normalized_doi}" if normalized_doi else None),
            "normalized_doi": normalized_doi,  # Used for comparison
            "display_name": result.get("display_name", ""),
            "authors": (
                result.get("hint", "").split(", ") if result.get("hint") else []
            ),
            "_score": result.get("cited_by_count", 0),
            "citations": result.get("cited_by_count", 0),
            "source": "openalex",
            "openalex_id": result.get("id"),  # OpenAlex ID from result
        }

    def transform_es_result(self, result):
        source = result.get("_source", {})
        normalized_doi = DOI.normalize_doi(source.get("doi"))
        return {
            "entity_type": "work",
            "id": source.get("id"),  # ResearchHub paper ID
            "doi": (f"{normalized_doi}" if normalized_doi else None),
            "normalized_doi": normalized_doi,  # Used for comparison
            "display_name": source.get("paper_title", ""),
            "authors": [
                author.get("full_name", "")
                for author in source.get("raw_authors", [])
                if author.get("full_name")
            ],
            "_score": result.get("_score", 0),
            "citations": source.get("citations", 0),
            "source": "researchhub",
            "openalex_id": source.get("openalex_id"),  # OpenAlex ID if exists in ES
        }

    def get(self, request):
        """
        Combined autocomplete search using both OpenAlex and local Elasticsearch.
        Query params:
        - q: search query (required)
        """
        query = request.query_params.get("q", None)
        if not query:
            return Response(
                {"error": "Search query is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # Get OpenAlex results
            openalex = OpenAlex()
            openalex_response = openalex.autocomplete_works(query)
            openalex_results = [
                self.transform_openalex_result(result)
                for result in openalex_response.get("results", [])
                if result.get(
                    "external_id"
                )  # Only include results with external_id (DOI)
            ]

            # Get local Elasticsearch results
            search = Search(index=PaperDocument._index._name)
            suggest = search.suggest(
                "suggestions", query, completion={"field": "suggestion_phrases"}
            )
            es_response = suggest.execute().suggest.to_dict()
            es_results = []
            for suggestion in es_response.get("suggestions", []):
                es_results.extend(
                    [
                        self.transform_es_result(option)
                        for option in suggestion.get("options", [])[:3]
                        if option.get("_source", {}).get(
                            "doi"
                        )  # Only include results with DOI
                    ]
                )

            # Combine results and deduplicate by DOI
            seen_dois = set()
            unique_results = []

            # First add ResearchHub results (all should have DOIs at this point)
            for result in sorted(
                es_results, key=lambda x: x.get("_score", 0), reverse=True
            ):
                doi = result.get("normalized_doi")
                seen_dois.add(doi)
                unique_results.append(result)

            # Then add OpenAlex results if DOI not already seen
            for result in sorted(
                openalex_results, key=lambda x: x.get("_score", 0), reverse=True
            ):
                doi = result.get("normalized_doi")
                if doi not in seen_dois:
                    seen_dois.add(doi)
                    unique_results.append(result)

            # Remove normalized_doi from results before sending response
            for result in unique_results:
                del result["normalized_doi"]

            return Response(unique_results, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
