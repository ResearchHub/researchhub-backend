import logging

from django.db.models import Q
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import (
    AllowAny,
    IsAuthenticated,
    IsAuthenticatedOrReadOnly,
)
from rest_framework.request import Request
from rest_framework.response import Response

from discussion.permissions import CensorDiscussion as CensorDiscussionPermission
from discussion.permissions import EditorCensorDiscussion
from discussion.views import ReactionViewActionMixin
from paper.exceptions import DOINotFoundError
from paper.models import Paper
from paper.permissions import (
    CanModifyLegacyJournalPaper,
    UpdatePaper,
    is_legacy_journal_paper,
)
from paper.related_models.authorship_model import Authorship
from paper.serializers import (
    DynamicPaperSerializer,
    PaperSerializer,
)
from user.content_moderation_mixin import ContentModerationActionsMixin
from user.permissions import IsModerator
from user.related_models.author_model import Author
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
        IsAuthenticatedOrReadOnly & UpdatePaper & CreateOrUpdateIfAllowed,
        CanModifyLegacyJournalPaper,
    ]

    def _prevent_legacy_journal_mutation(self, paper_id: str | None) -> None:
        """Reject mutations that target an existing legacy journal paper."""
        if is_legacy_journal_paper(paper_id):
            raise PermissionDenied(CanModifyLegacyJournalPaper.message)

    @action(detail=True, methods=["post"], permission_classes=[IsModerator])
    def approve(self, request: Request, pk: str | None = None) -> Response:
        """Approve a paper that is not part of the retired journal."""
        self._prevent_legacy_journal_mutation(pk)
        return super().approve(request, pk)

    @action(detail=True, methods=["post"], permission_classes=[IsModerator])
    def decline(self, request: Request, pk: str | None = None) -> Response:
        """Decline a paper that is not part of the retired journal."""
        self._prevent_legacy_journal_mutation(pk)
        return super().decline(request, pk)

    @action(
        detail=True,
        methods=["put", "patch", "delete"],
        permission_classes=[
            IsAuthenticated,
            (CensorDiscussionPermission | EditorCensorDiscussion),
        ],
    )
    def censor(
        self,
        request: Request,
        *args: object,
        pk: str | None = None,
        **kwargs: object,
    ) -> Response:
        """Censor a paper that is not part of the retired journal."""
        self._prevent_legacy_journal_mutation(pk)
        return super().censor(request, *args, pk=pk, **kwargs)

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
                        (
                            rh_author_first_name == openalex_author_name[0]
                            and rh_author_last_name == openalex_author_name[-1]
                        )
                        or (
                            found_openalex_author is None
                            and rh_author_last_name == openalex_author_name[0]
                        )
                        or (
                            found_openalex_author is None
                            and rh_author_first_name == openalex_author_name[-1]
                        )
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
