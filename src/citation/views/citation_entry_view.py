from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from citation.constants import CITATION_TYPE_FIELDS
from citation.models import CitationEntry
from citation.schema import generate_schema_for_citation
from citation.serializers import CitationEntrySerializer
from paper.utils import clean_dois
from utils.openalex import OpenAlex


class CitationEntryViewSet(ModelViewSet):
    queryset = CitationEntry.objects.all()
    permission_classes = [IsAuthenticated]
    serializer_class = CitationEntrySerializer
    ordering = ["-created_date"]

    def create(self, request, *args, **kwargs):
        data = request.data
        data["created_by"] = request.user.id
        res = super().create(request, *args, **kwargs)
        return res

    def update(self, request, *args, **kwargs):
        data = request.data
        data["created_by"] = request.user.id
        data["updated_by"] = request.user.id
        res = super().update(request)
        return res

    def list(self, request):
        pass

    def retrieve(self, request):
        pass

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated])
    def user_citations(self, request):
        user = request.user
        citations = user.created_citation_citationentry.all().order_by("-created_date")
        page = self.paginate_queryset(citations)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(citations, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"], permission_classes=[AllowAny])
    def get_schema_for_citation(self, request):
        query_params = request.query_params
        citation_type = query_params.get("citation_type", None)
        if citation_type not in CITATION_TYPE_FIELDS:
            return Response(
                {"error": "Provided citation type does not exist"}, status=400
            )
        schema = generate_schema_for_citation(citation_type)
        return Response(schema)

    @action(detail=False, methods=["get"], permission_classes=[AllowAny])
    def get_citation_types(self, request):
        citation_types = CITATION_TYPE_FIELDS.keys()
        return Response(citation_types)

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated])
    def doi_search(self, request):
        doi_string = request.query_params.get("doi", None)
        open_alex = OpenAlex()
        result = open_alex.get_data_from_doi(doi_string)
        return Response(result, status=200)