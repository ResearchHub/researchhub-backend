from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from citation.constants import CITATION_TYPE_FIELDS
from citation.filters import CitationEntryFilter
from citation.models import CitationEntry
from citation.schema import generate_schema_for_citation
from citation.serializers import CitationEntrySerializer
from citation.tasks import handle_creating_citation_entry
from utils.aws import upload_to_s3
from utils.openalex import OpenAlex


class CitationEntryViewSet(ModelViewSet):
    queryset = CitationEntry.objects.all()
    filter_class = CitationEntryFilter
    filter_backends = (DjangoFilterBackend, OrderingFilter)
    permission_classes = [IsAuthenticated]
    serializer_class = CitationEntrySerializer
    ordering = ("-updated_date", "-created_date")
    ordering_fields = ("updated_date", "created_date")

    def list(self, request):
        pass

    def retrieve(self, request):
        pass

    @action(detail=False, methods=["post"], permission_classes=[IsAuthenticated])
    def pdf_uploads(self, request):
        pdfs = request.FILES.getlist("pdfs[]")
        created = []
        for pdf in pdfs:
            url = upload_to_s3(pdf, "citation_pdfs")
            path = url.split(".com/")[1]
            handle_creating_citation_entry.apply_async(
                (
                    path,
                    request.user.id,
                    request.data.get("organization_id"),
                    request.data.get("project_id"),
                ),
                priority=5,
            )

        return Response({"created": created}, 200)

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated])
    def user_citations(self, request):
        # Using .none() to return an empty queryset if org/proj id is not passed in
        qs = self.filter_queryset(self.get_queryset().none())

        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(qs, many=True)
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
