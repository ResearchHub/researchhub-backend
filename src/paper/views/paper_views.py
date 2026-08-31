import logging

from django.db.models import Q
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import (
    AllowAny,
    IsAuthenticatedOrReadOnly,
)
from rest_framework.response import Response

from discussion.views import ReactionViewActionMixin
from paper.models import Paper
from paper.permissions import UpdatePaper
from paper.serializers import (
    DynamicPaperSerializer,
    PaperSerializer,
)
from user.content_moderation_mixin import ContentModerationActionsMixin
from user.views.follow_view_mixins import FollowViewActionMixin
from utils.doi import DOI
from utils.openalex import OpenAlex
from utils.permissions import CreateOrUpdateIfAllowed
from utils.throttles import THROTTLE_CLASSES

logger = logging.getLogger(__name__)


class PaperViewSet(
    ContentModerationActionsMixin,
    ReactionViewActionMixin,
    FollowViewActionMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Paper.objects.all()
    serializer_class = PaperSerializer
    dynamic_serializer_class = DynamicPaperSerializer
    throttle_classes = THROTTLE_CLASSES
    moderation_model = Paper

    permission_classes = [
        IsAuthenticatedOrReadOnly & UpdatePaper & CreateOrUpdateIfAllowed
    ]

    def prefetch_lookups(self):
        return (
            "uploaded_by",
            "uploaded_by__author_profile",
            "uploaded_by__author_profile__user",
            "authors",
            "authors__user",
            "authors__user__userverification",
            "unified_document",
            "unified_document__hubs",
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
