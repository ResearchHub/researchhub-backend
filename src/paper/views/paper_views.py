import logging
from urllib.parse import urlparse

import requests
from django.contrib.admin.options import get_content_type_for_model
from django.db import IntegrityError
from django.db.models import Q
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import (
    AllowAny,
    IsAuthenticated,
    IsAuthenticatedOrReadOnly,
)
from rest_framework.response import Response

from analytics.amplitude import track_event
from discussion.models import Vote
from discussion.serializers import VoteSerializer
from discussion.views import ReactionViewActionMixin
from paper.exceptions import DOINotFoundError, PaperSerializerError
from paper.filters import PaperFilter
from paper.models import Paper, PaperSubmission
from paper.paper_upload_tasks import celery_process_paper
from paper.permissions import CreatePaper, UpdatePaper
from paper.related_models.authorship_model import Authorship
from paper.serializers import (
    DynamicPaperSerializer,
    PaperSerializer,
    PaperSubmissionSerializer,
)
from user.content_moderation_mixin import ContentModerationActionsMixin
from user.related_models.author_model import Author
from user.views.follow_view_mixins import FollowViewActionMixin
from utils.doi import DOI
from utils.openalex import OpenAlex
from utils.permissions import CreateOrUpdateIfAllowed, PostOnly
from utils.throttles import THROTTLE_CLASSES

logger = logging.getLogger(__name__)


class PaperViewSet(
    ContentModerationActionsMixin,
    ReactionViewActionMixin,
    FollowViewActionMixin,
    viewsets.ModelViewSet,
):
    queryset = Paper.objects.all()
    serializer_class = PaperSerializer
    dynamic_serializer_class = DynamicPaperSerializer
    filter_backends = (SearchFilter, DjangoFilterBackend, OrderingFilter)
    search_fields = ("title", "doi", "paper_title")
    filterset_class = PaperFilter
    throttle_classes = THROTTLE_CLASSES
    ordering = "-created_date"
    moderation_model = Paper

    permission_classes = [
        IsAuthenticatedOrReadOnly & CreatePaper & UpdatePaper & CreateOrUpdateIfAllowed
    ]

    def prefetch_lookups(self):
        return (
            "uploaded_by",
            "uploaded_by__author_profile",
            "uploaded_by__author_profile__user",
            "uploaded_by__subscribed_hubs",
            "authors",
            "authors__user",
            "authors__user__userverification",
            "unified_document",
            "unified_document__hubs",
            "unified_document__hubs__subscribers",
            "votes",
            "flags",
            "purchases",
            "figures",
        )

    def get_queryset(self, prefetch=True):
        query_params = self.request.query_params
        queryset = self.queryset
        ordering = query_params.get("ordering", None)
        external_source = query_params.get("external_source", False)

        if (
            query_params.get("make_public")
            or query_params.get("all")
            or (ordering and "removed" in ordering)
        ):
            pass
        else:
            queryset = queryset.filter(is_removed=False)

        user = self.request.user
        if user.is_staff:
            return queryset

        # Papers that have not yet been approved (pending or declined) are not
        # publicly viewable (including via a direct link); only the uploader and
        # moderators / hub editors may see them until they are approved.
        queryset = queryset.visible_to(user)

        if not user.is_anonymous and user.moderator and external_source:
            queryset = queryset.filter(
                is_removed=False, retrieved_from_external_source=True
            )
        if prefetch:
            return queryset.prefetch_related(*self.prefetch_lookups())
        else:
            return queryset

    @track_event
    def create(self, request, *args, **kwargs):
        try:
            doi = request.data.get("doi", "")
            duplicate_papers = Paper.objects.filter(doi=doi)
            if duplicate_papers:
                serializer = DynamicPaperSerializer(
                    duplicate_papers[:1],
                    _include_fields=["doi", "id", "title", "url"],
                    many=True,
                )
                duplicate_data = {"data": serializer.data}
                return Response(duplicate_data, status=status.HTTP_403_FORBIDDEN)
            response = super().create(request, *args, **kwargs)
            return response
        except IntegrityError as e:
            return self._get_integrity_error_response(e)
        except PaperSerializerError:
            logger.exception("Failed to serialize paper")
            return Response(
                "Failed to serialize paper", status=status.HTTP_400_BAD_REQUEST
            )

    def _get_integrity_error_response(self, error):
        error_message = str(error)
        parts = error_message.split("DETAIL:")
        try:
            error_message = parts[1].strip()
            if "url" in error_message:
                error_message = "A paper with this url already exists."
            if "doi" in error_message:
                error_message = "A paper with this DOI already exists."
            if "DOI" in error_message:
                error_message = "Invalid DOI"
        except IndexError:
            error_message = "A paper with this url or DOI already exists."
        return Response({"error": error_message}, status=status.HTTP_400_BAD_REQUEST)

    def _get_paper_context(self, request=None):
        context = {
            "request": request,
            "doc_duds_get_documents": {"_include_fields": ["id"]},
            "pap_dps_get_unified_document": {
                "_include_fields": [
                    "id",
                    "reviews",
                    "is_removed",
                    "document_type",
                    "documents",
                ]
            },
            "pap_dps_get_user_vote": {},
            "pap_dps_get_uploaded_by": {
                "_include_fields": [
                    "id",
                    "author_profile",
                    "first_name",
                    "last_name",
                    "is_verified",
                ]
            },
            "usr_dus_get_author_profile": {
                "_include_fields": [
                    "id",
                    "first_name",
                    "last_name",
                    "profile_image",
                    "is_verified",
                ]
            },
            "doc_duds_get_concepts": {
                "_include_fields": ["openalex_id", "display_name", "description"]
            },
            "pap_dps_get_hubs": {
                "_exclude_fields": [
                    "editor_permission_groups",
                    "subscribers",
                    "subscriber_count",
                    "paper_count",
                    "discussion_count",
                ]
            },
            "pap_dbs_get_bounties": {
                "_include_fields": [
                    "amount",
                    "created_by",
                    "expiration_date",
                    "id",
                    "status",
                ]
            },
            "pap_dps_get_peer_reviews": {
                "_include_fields": [
                    "id",
                    "score",
                    "is_assessed",
                    "created_by",
                    "created_date",
                    "updated_date",
                ]
            },
            "rev_drs_get_created_by": {
                "_include_fields": [
                    "id",
                    "author_profile",
                    "first_name",
                    "last_name",
                ]
            },
            "pap_dps_get_purchases": {"_include_fields": ["amount", "user"]},
            "rep_dbs_get_created_by": {"_include_fields": ["author_profile", "id"]},
            "pch_dps_get_user": {
                "_include_fields": [
                    "id",
                    "author_profile",
                    "first_name",
                    "last_name",
                ]
            },
        }
        return context

    def _serialize_paper(self, paper, request):
        """
        Common serialization method for papers.
        Used by both retrieve and retrieve_by_doi endpoints.
        """
        context = self._get_paper_context(request)
        serializer = self.dynamic_serializer_class(
            paper,
            context=context,
            _include_fields=[
                "abstract",
                "authors",
                "boost_amount",
                "created_date",
                "discussion_count",
                "doi",
                "external_source",
                "file",
                "first_preview",
                "id",
                "is_open_access",
                "oa_status",
                "paper_publish_date",
                "paper_title",
                "pdf_license",
                "pdf_url",
                "pdf_copyright_allows_display",
                "peer_reviews",
                "purchases",
                "raw_authors",
                "score",
                "adjusted_score",
                "slug",
                "title",
                "work_type",
                "unified_document",
                "uploaded_by",
                "uploaded_date",
                "url",
                "version",
                "version_list",
            ],
        )
        serializer_data = serializer.data
        vote = self.dynamic_serializer_class(context=context).get_user_vote(paper)
        serializer_data["user_vote"] = vote
        return serializer_data

    def retrieve(self, request, *args, **kwargs):
        """
        Retrieve a paper by ID.
        """
        paper = super().get_object()
        serializer_data = self._serialize_paper(paper, request)
        return Response(serializer_data)

    def list(self, request, *args, **kwargs):
        # Temporarily disabling endpoint
        return Response(status=200)

    @action(detail=True, methods=["get"])
    def user_vote(self, request, pk=None):
        paper = self.get_object()
        user = request.user
        vote = retrieve_vote(user, paper)
        serializer = VoteSerializer(vote)
        return Response(serializer.data, status=200)

    @user_vote.mapping.delete
    def delete_user_vote(self, request, pk=None):
        try:
            paper = self.get_object()
            user = request.user
            vote = retrieve_vote(user, paper)
            vote_id = vote.id
            vote.delete()
            return Response(vote_id, status=200)
        except Exception as e:
            return Response(f"Failed to delete vote: {e}", status=400)

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated])
    def fetch_publications_by_doi(self, request):
        doi_string = request.query_params.get("doi", "")
        rh_author = request.user.author_profile

        # Client has the ability (optional) to specify explicilty which OpenAlex ID it
        # wants works for
        openalex_author_id = request.query_params.get("author_id", None)

        if doi_string is None:
            return Response(status=400)

        try:
            # Sometimes user may pass in a doi as doi.org url.
            doi_string = doi_string.replace("https://doi.org/", "").strip()

            try:
                # Fetch data from OpenAlex
                open_alex_api = OpenAlex()
                work = open_alex_api.get_data_from_doi(doi_string)
            except DOINotFoundError:
                return Response(status=404)

            # Next we want to try and guess the author in the list of authors associated
            # with the work.
            # The guess doesn't have to be precise since the user will have the ability
            # to select the correct author.
            # In case we can't guess the author, we will return an error.
            if not openalex_author_id:
                for authorship in work.get("authorships", []):
                    found_openalex_author = None
                    openalex_author = authorship.get("author", {})
                    openalex_author_name = (
                        openalex_author.get("display_name", "").lower().split(" ")
                    )

                    rh_author_first_name = (rh_author.first_name or "").lower()
                    rh_author_last_name = (rh_author.last_name or "").lower()

                    if (
                        rh_author_first_name == openalex_author_name[0]
                        and rh_author_last_name == openalex_author_name[-1]
                    ):
                        found_openalex_author = openalex_author
                    elif (
                        found_openalex_author is None
                        and rh_author_last_name == openalex_author_name[0]
                    ):
                        found_openalex_author = openalex_author
                    elif (
                        found_openalex_author is None
                        and rh_author_first_name == openalex_author_name[-1]
                    ):
                        found_openalex_author = openalex_author

                    if found_openalex_author:
                        openalex_author_id = found_openalex_author.get("id", "")

            # Fetch author works
            author_works = []
            if openalex_author_id:
                openalex_author_id = openalex_author_id.split("/")[-1]
                author_works, _ = open_alex_api.get_works(
                    openalex_author_id=openalex_author_id, batch_size=200
                )
            unclaimed_works = self._filter_unclaimed_works(rh_author, author_works)

            response = {
                "works": unclaimed_works,
                "selected_author_id": openalex_author_id,
                "available_authors": [
                    authorship.get("author")
                    for authorship in work.get("authorships", [])
                ],
            }

            return Response(response, status=200)
        except Exception:
            logger.exception(
                "Error fetching publications by DOI", extra={"doi": doi_string}
            )
            return Response(status=500)

    def _filter_unclaimed_works(self, author: Author, openalex_works: list) -> list:
        """
        Returns a list of works that the author has not claimed yet.
        """
        authorships = Authorship.objects.filter(author=author)
        claimed_works = Paper.objects.filter(
            id__in=authorships.values_list("paper_id", flat=True)
        ).values_list("openalex_id", flat=True)
        unclaimed_works = list(
            filter(lambda work: work["id"] not in claimed_works, openalex_works)
        )
        return unclaimed_works

    @action(
        detail=False,
        methods=["get"],
        permission_classes=[AllowAny],
    )
    def retrieve_by_doi(self, request):
        """
        Get a paper by DOI or create it if it doesn't exist by importing from OpenAlex.
        Query params:
        - doi: string (required) - The DOI to look up
        """
        doi = request.query_params.get("doi")
        if not doi:
            return Response(
                {"error": "DOI is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validate DOI format first
        if not DOI.is_doi(doi):
            return Response(
                {"error": "Invalid DOI format"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # Get bare DOI for database lookup
            bare_doi = DOI.get_bare_doi(doi)
            if not bare_doi:
                return Response(
                    {"error": "Invalid DOI format"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Look for existing paper with this DOI
            paper = Paper.objects.filter(Q(doi=bare_doi)).first()
            if paper:
                serializer_data = self._serialize_paper(paper, request)
                return Response(serializer_data)

            # Paper doesn't exist, try to import it from OpenAlex
            return self._create_by_doi(request, doi=bare_doi)

        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def _create_by_doi(self, request, doi):
        """
        Create a paper by fetching data from OpenAlex using a DOI.
        Args:
            doi: Bare DOI (without https://doi.org/ prefix)
        """
        try:
            # Fetch work from OpenAlex
            openalex = OpenAlex()
            work = openalex.get_work_by_doi(doi)
            if not work:
                return Response(
                    {"error": "Work not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            # Process the work
            from paper.openalex_util import process_openalex_works

            process_openalex_works([work])

            # Get the created paper and serialize it
            paper = Paper.objects.get(doi=doi)
            serializer_data = self._serialize_paper(paper, request)
            return Response(serializer_data, status=status.HTTP_201_CREATED)

        except Exception:
            logger.exception("Error creating paper by DOI", extra={"doi": doi})
            return Response(
                {"error": "An error occurred while creating the paper."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


def retrieve_vote(user, paper):
    try:
        return Vote.objects.get(
            content_type=get_content_type_for_model(paper),
            created_by=user,
            object_id=paper.id,
        )
    except Vote.DoesNotExist:
        return None


class PaperSubmissionViewSet(viewsets.ModelViewSet):
    queryset = PaperSubmission.objects.all()
    serializer_class = PaperSubmissionSerializer
    throttle_classes = THROTTLE_CLASSES
    permission_classes = [IsAuthenticated, PostOnly]

    @track_event
    def create(self, *args, **kwargs):
        data = self.request.data
        url = data.get("url", "")

        # Appends http if protocol does not exist
        parsed_url = urlparse(url)
        if not parsed_url.scheme:
            url = f"http://{parsed_url.geturl()}"
            data["url"] = url

        duplicate_papers = Paper.objects.filter(
            Q(url__iexact=url) | Q(pdf_url__iexact=url)
        )

        if duplicate_papers:
            serializer = DynamicPaperSerializer(
                duplicate_papers,
                _include_fields=[
                    "doi",
                    "id",
                    "title",
                    "url",
                    "uploaded_by",
                    "created_date",
                ],
                context={
                    "pap_dps_get_uploaded_by": {
                        "_include_fields": ("id", "first_name", "last_name")
                    }
                },
                many=True,
            )
            duplicate_data = {"data": serializer.data}
            return Response(duplicate_data, status=status.HTTP_403_FORBIDDEN)

        data["uploaded_by"] = self.request.user.id
        response = super().create(*args, **kwargs)
        if response.status_code == 201:
            data = response.data
            celery_process_paper(data["id"])
        return response

    @track_event
    @action(detail=False, methods=["post"])
    def create_from_doi(self, request):
        data = request.data
        # TODO: Sanitize?
        doi = data.get("doi", None)
        # DOI validity check
        doi_url = urlparse(doi)
        doi_res = requests.post(
            "https://dx.doi.org/", data={"hdl": doi}, allow_redirects=False, timeout=5
        )
        invalid_doi_res = Response(
            {"data": "Invalid DOI - Ensure it is in the form of '10.1000/abc123'"},
            status=status.HTTP_404_NOT_FOUND,
        )
        if doi_url.scheme or "doi.org" in doi:
            # Avoiding data that comes in as a url or as a DOI url
            return invalid_doi_res
        elif doi_res.status_code == status.HTTP_404_NOT_FOUND:
            return invalid_doi_res

        # Duplicate DOI check
        duplicate_papers = Paper.objects.filter(doi__iexact=doi)

        if duplicate_papers:
            serializer = DynamicPaperSerializer(
                duplicate_papers,
                _include_fields=["doi", "id", "title", "url"],
                many=True,
            )
            duplicate_data = {"data": serializer.data}
            return Response(duplicate_data, status=status.HTTP_403_FORBIDDEN)

        data["uploaded_by"] = request.user.id
        response = super().create(request)
        if response.status_code == 201:
            data = response.data
            celery_process_paper(data["id"])
        return response
