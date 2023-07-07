import cloudscraper
import re

from boto3 import session
from bs4 import BeautifulSoup
from collections import Counter
from django_filters.rest_framework import DjangoFilterBackend
from django.db import transaction
from django.utils.crypto import get_random_string
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet
from urllib.parse import urlparse

from citation.constants import CITATION_TYPE_FIELDS
from citation.filters import CitationEntryFilter
from citation.models import CitationEntry
from citation.permissions import PDFUploadsS3CallBack
from citation.schema import generate_schema_for_citation
from citation.serializers import CitationEntrySerializer
from paper.exceptions import DOINotFoundError
from paper.utils import clean_dois
from citation.tasks import handle_creating_citation_entry
from researchhub.pagination import FasterDjangoPaginator
from researchhub.settings import AWS_STORAGE_BUCKET_NAME
from utils.openalex import OpenAlex
from utils.parsers import clean_filename


class CitationEntryPagination(PageNumberPagination):
    django_paginator_class = FasterDjangoPaginator
    page_size_query_param = "page_size"
    max_page_size = 10000
    page_size = 1000


class CitationEntryViewSet(ModelViewSet):
    queryset = CitationEntry.objects.all()
    filter_class = CitationEntryFilter
    filter_backends = (DjangoFilterBackend, OrderingFilter)
    permission_classes = [IsAuthenticated]
    serializer_class = CitationEntrySerializer
    pagination_class = CitationEntryPagination
    ordering = ("-updated_date", "-created_date")
    ordering_fields = ("updated_date", "created_date")

    def list(self, request):
        return Response(
            "Method not allowed. Use user_citations instead",
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def retrieve(self, request):
        return Response(
            "Method not allowed. Use user_citations instead",
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    @action(detail=False, methods=["post"], permission_classes=[IsAuthenticated])
    def upload_pdfs(self, request):
        data = request.data
        organization_id = data.get("organization_id")
        project_id = data.get("project_id")
        filename = data.get("filename")

        cleaned_filename = clean_filename(f"{get_random_string(8)}_{filename}")
        user_key = f"user_{request.user.id}"
        boto3_session = session.Session()
        s3_client = boto3_session.client("s3")
        ascii_cleaned_filename = filename.encode("ascii", "ignore").decode()

        res = s3_client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": AWS_STORAGE_BUCKET_NAME,
                "Key": f"uploads/citation_pdfs/{user_key}_{cleaned_filename}",
                "ContentType": "application/pdf",
                "Metadata": {
                    "x-amz-meta-created-by-id": f"{request.user.id}",
                    "x-amz-meta-organization-id": f"{organization_id}",
                    "x-amz-meta-project-id": f"{project_id}",
                    "x-amz-meta-file-name": ascii_cleaned_filename,
                },
            },
            ExpiresIn=60 * 2,
        )
        return Response(res, status=200)

    @action(detail=False, methods=["post"], permission_classes=[PDFUploadsS3CallBack])
    def upload_pdfs_callback(self, request):
        data = request.data
        path = data.get("path")
        filename = data.get("filename")
        organization_id = data.get("organization_id")
        project_id = data.get("project_id")
        creator_id = data.get("creator_id")

        # Temporary condition to use Grobid or pdf2doi
        use_grobid = data.get("use_grobid", "False") == "True"

        if project_id == "None" or project_id is None:
            project_id = None

        handle_creating_citation_entry.apply_async(
            (path, filename, creator_id, organization_id, project_id, use_grobid),
            priority=5,
            countdown=0.1,
        )
        return Response(status=200)

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated])
    def user_citations(self, request):
        citations_query = self.filter_queryset(self.get_queryset().none()).order_by(
            *self.ordering
        )

        # page = self.paginate_queryset(qs)
        # if page is not None:
        #     serializer = self.get_serializer(page, many=True)
        #     return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(citations_query, many=True)
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

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated])
    def url_search(self, request):
        try:
            url_string = request.query_params.get("url", None)
            scraper_result = cloudscraper.create_scraper().get(url_string)
            status_code = scraper_result.status_code
            dois = []

            if status_code >= 200 and status_code < 400:
                content = BeautifulSoup(scraper_result.content, "lxml")
                dois = re.findall(
                    r"10.\d{4,9}\/[-._;()\/:a-zA-Z0-9]+?(?=[\";%<>\?#&])", str(content)
                )
                parsed_url = urlparse(url_string)
                cleaned_dois = clean_dois(parsed_url, list(map(str.strip, dois)))
                doi_counter = Counter(cleaned_dois)
                formmated_dois = [doi for doi, _ in doi_counter.most_common(1)]

                open_alex = OpenAlex()
                open_alex_result = open_alex.get_data_from_doi(formmated_dois[0])

                return Response(open_alex_result, status=200)
        except Exception as error:
            return Response({"result": "DOI / URL not found"}, status=400)

    @action(
        detail=False,
        methods=["POST", "DELETE"],
        permission_classes=[IsAuthenticated],
    )
    def remove(self, request, *args, **kwargs):
        with transaction.atomic():
            try:
                target_citation_ids = request.data.get("citation_entry_ids", [])
                current_user = request.user
                for citation_id in target_citation_ids:
                    target_ref = CitationEntry.objects.get(id=citation_id)
                    if target_ref.is_user_allowed_to_edit(current_user):
                        target_ref.delete()
                return Response(target_citation_ids, status=status.HTTP_200_OK)

            except Exception as error:
                return Response(error, status=status.HTTP_400_BAD_REQUEST)
