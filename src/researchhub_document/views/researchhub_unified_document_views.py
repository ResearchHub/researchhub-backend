from functools import wraps

from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from discussion.models import Vote
from discussion.serializers import VoteSerializer
from paper.models import Paper
from researchhub_document.models import ResearchhubPost, ResearchhubUnifiedDocument
from researchhub_document.serializers import (
    DynamicUnifiedDocumentSerializer,
    ResearchhubUnifiedDocumentSerializer,
    UnifiedDocumentShareLinkSerializer,
)
from researchhub_document.serializers.excluded_from_feed_serializer import (
    ExcludedFromFeedWorkSerializer,
)
from researchhub_document.services.unified_document_feed_visibility_service import (
    UnifiedDocumentFeedVisibilityService,
)
from researchhub_document.services.unified_document_share_link_service import (
    UnifiedDocumentShareLinkService,
    get_shared_unified_document_id,
)
from user.permissions import IsModerator
from utils.permissions import ReadOnly


class ExcludedFromFeedPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


def _share_link_errors_to_responses(handler):
    """Translate share-link service failures into HTTP responses.

    Keeps the three share_link handlers free of identical guard clauses. The
    id is screened here so a malformed one answers 404 rather than reaching
    the ValueError branch, which is reserved for rejected requests.
    """

    @wraps(handler)
    def wrapper(self, request, pk=None):
        if pk is None or not str(pk).isdigit():
            return Response(status=status.HTTP_404_NOT_FOUND)

        try:
            return handler(self, request, pk)
        except ResearchhubUnifiedDocument.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        except PermissionError as error:
            return Response({"detail": str(error)}, status=status.HTTP_403_FORBIDDEN)
        except ValueError as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)

    return wrapper


class ResearchhubUnifiedDocumentViewSet(GenericViewSet):
    permission_classes = [
        IsAuthenticated | ReadOnly,
    ]
    dynamic_serializer_class = DynamicUnifiedDocumentSerializer
    queryset = ResearchhubUnifiedDocument.objects.all()
    serializer_class = ResearchhubUnifiedDocumentSerializer

    def _get_serializer_context(self):
        context = {
            "doc_duds_get_documents": {
                "_include_fields": [
                    "abstract",
                    "created_by",
                    "created_date",
                    "discussion_count",
                    "file",
                    "first_preview",
                    "id",
                    "external_source",
                    "paper_publish_date",
                    "paper_title",
                    "pdf_url",
                    "image_url",
                    "is_open_access",
                    "oa_status",
                    "pdf_copyright_allows_display",
                    "authors",
                    "preview_img",
                    "renderable_text",
                    "slug",
                    "title",
                    "uploaded_by",
                    "uploaded_date",
                    "citations",
                    "authorships",
                    "work_type",
                ]
            },
            "doc_duds_get_hubs": {
                "_include_fields": [
                    "id",
                    "name",
                    "is_locked",
                    "slug",
                    "is_removed",
                    "hub_image",
                ],
            },
            "pap_dps_get_authorships": {
                "_include_fields": [
                    "id",
                    "author",
                    "author_position",
                    "author_id",
                    "raw_author_name",
                    "is_corresponding",
                ]
            },
            "authorship::get_author": {"_include_fields": ["id", "profile_image"]},
            "doc_dps_get_created_by": {
                "_include_fields": [
                    "id",
                    "author_profile",
                ]
            },
            "pap_dps_get_uploaded_by": {
                "_include_fields": [
                    "id",
                    "author_profile",
                ]
            },
            "pap_dps_get_authors": {
                "_include_fields": ["id", "first_name", "last_name"]
            },
            "doc_duds_get_fundraise": {
                "_include_fields": [
                    "id",
                    "status",
                    "goal_amount",
                    "goal_currency",
                    "start_date",
                    "end_date",
                    "amount_raised",
                    "contributors",
                ]
            },
            "doc_duds_get_grant": {
                "_include_fields": [
                    "id",
                    "status",
                    "amount",
                    "currency",
                    "organization",
                    "description",
                    "start_date",
                    "end_date",
                    "created_by",
                    "contacts",
                    "applications",
                    "application_visibility",
                ]
            },
            "pch_dfs_get_contributors": {
                "_include_fields": [
                    "id",
                    "author_profile",
                    "first_name",
                    "last_name",
                ]
            },
            "pch_dgs_get_created_by": {
                "_include_fields": [
                    "id",
                    "author_profile",
                    "first_name",
                    "last_name",
                ]
            },
            "pch_dgs_get_contacts": {
                "_include_fields": [
                    "id",
                    "author_profile",
                    "first_name",
                    "last_name",
                ]
            },
            "usr_dus_get_author_profile": {
                "_include_fields": [
                    "id",
                    "first_name",
                    "last_name",
                    "created_date",
                    "updated_date",
                    "profile_image",
                    "is_verified",
                ]
            },
        }
        return context

    @action(
        detail=True,
        methods=["post"],
        permission_classes=[IsAuthenticated],
        url_path="share_link",
    )
    @_share_link_errors_to_responses
    def share_link(self, request, pk=None):
        """Return the proposal's share link, generating one when needed.

        Regenerates an expired link, so callers must only hit this on an
        explicit user action and never on page render. Use GET to read a link
        without minting one.
        """
        link, created = UnifiedDocumentShareLinkService().create_or_get(
            pk, request.user
        )
        return Response(
            UnifiedDocumentShareLinkSerializer(link).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @share_link.mapping.get
    @_share_link_errors_to_responses
    def get_share_link(self, request, pk=None):
        """Return the proposal's live share link without generating one.

        Answers 404 when sharing is off or the link has lapsed, so callers see
        the same thing either way.
        """
        link = UnifiedDocumentShareLinkService().get_live_link(pk, request.user)
        if link is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        return Response(UnifiedDocumentShareLinkSerializer(link).data)

    @share_link.mapping.delete
    @_share_link_errors_to_responses
    def disable_share_link(self, request, pk=None):
        """Turn sharing off, invalidating any link already handed out.

        Idempotent: answers 204 whether or not a link existed, so a toggle can
        call it without first checking.
        """
        UnifiedDocumentShareLinkService().disable(pk, request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(
        detail=True,
        methods=["post"],
        permission_classes=[IsAuthenticated, IsModerator],
        url_path="exclude_from_feed",
    )
    def exclude_from_feed(self, request, pk=None):
        """Hide this document from public feeds. Idempotent and feed-only."""
        return self._set_feed_visibility(request, pk, excluded=True)

    @action(
        detail=True,
        methods=["post"],
        permission_classes=[IsAuthenticated, IsModerator],
        url_path="include_in_feed",
    )
    def include_in_feed(self, request, pk=None):
        """Restore this document to public feeds. Idempotent and feed-only."""
        return self._set_feed_visibility(request, pk, excluded=False)

    def _set_feed_visibility(self, request, pk, excluded: bool):
        if pk is None or not str(pk).isdigit():
            return Response(status=status.HTTP_404_NOT_FOUND)

        service = UnifiedDocumentFeedVisibilityService()
        try:
            if excluded:
                unified_document = service.exclude_from_feed(int(pk), request.user)
            else:
                unified_document = service.include_in_feed(int(pk), request.user)
        except ResearchhubUnifiedDocument.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        except PermissionError as error:
            return Response({"detail": str(error)}, status=status.HTTP_403_FORBIDDEN)

        return Response(
            {
                "id": unified_document.id,
                "is_excluded_in_feed": (
                    unified_document.document_filter.is_excluded_in_feed
                ),
            }
        )

    @action(
        detail=False,
        methods=["get"],
        permission_classes=[IsAuthenticated, IsModerator],
        url_path="excluded_from_feed",
    )
    def excluded_from_feed(self, request):
        """Paginated Work payloads for documents currently hidden from feeds."""
        queryset = UnifiedDocumentFeedVisibilityService().list_excluded_from_feed(
            query=request.query_params.get("query")
        )
        paginator = ExcludedFromFeedPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        serializer = ExcludedFromFeedWorkSerializer(
            page, many=True, context={"request": request}
        )
        return paginator.get_paginated_response(serializer.data)

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated])
    def check_user_vote(self, request):
        paper_ids = request.query_params.get("paper_ids", "")
        post_ids = request.query_params.get("post_ids", "")

        if paper_ids:
            paper_ids = paper_ids.split(",")
        if post_ids:
            post_ids = post_ids.split(",")

        if len(paper_ids) > 1 or len(post_ids) > 1:
            return Response(
                {"detail": "Only one id is allowed per request."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = request.user
        response = {
            "paper": {},
            "posts": {},
        }

        # TODO: Refactor below
        if paper_ids:
            paper_votes = _get_user_votes(
                user, paper_ids, ContentType.objects.get_for_model(Paper)
            )
            for vote in paper_votes.iterator():
                paper_id = vote.object_id
                response["paper"][paper_id] = VoteSerializer(instance=vote).data
        if post_ids:
            post_votes = _get_user_votes(
                user, post_ids, ContentType.objects.get_for_model(ResearchhubPost)
            )
            for vote in post_votes.iterator():
                response["posts"][vote.object_id] = VoteSerializer(instance=vote).data
        return Response(response, status=status.HTTP_200_OK)

    def _get_document_metadata_context(self):
        context = self.get_serializer_context()
        bounties_context_fields = ("id", "amount", "created_by", "status")
        bounties_select_related_fields = ("created_by", "created_by__author_profile")
        discussion_context_fields = ("id", "comment_count", "thread_type")
        purchase_context_fields = ("id", "amount", "user")
        purchase_select_related_fields = ("user", "user__author_profile")
        metadata_context = {
            **context,
            "doc_duds_get_documents": {
                "_include_fields": (
                    "bounties",
                    "discussion_aggregates",
                    "purchases",
                    "user_vote",
                )
            },
            "doc_dps_get_bounties": {"_include_fields": bounties_context_fields},
            "doc_dps_get_bounties_select": bounties_select_related_fields,
            "doc_dps_get_discussions": {"_include_fields": discussion_context_fields},
            "doc_dps_get_discussions_prefetch": ("rh_comments",),
            "doc_dps_get_purchases": {"_include_fields": purchase_context_fields},
            "doc_dps_get_purchases_select": purchase_select_related_fields,
            "pap_dps_get_bounties": {"_include_fields": bounties_context_fields},
            "pap_dps_get_bounties_select": bounties_select_related_fields,
            "pap_dps_get_discussions": {"_include_fields": discussion_context_fields},
            "pap_dps_get_discussions_prefetch": ("rh_comments",),
            "pap_dps_get_purchases": {"_include_fields": purchase_context_fields},
            "pch_dps_get_user": {
                "_include_fields": [
                    "id",
                    "author_profile",
                    "first_name",
                    "last_name",
                ]
            },
            "rep_dbs_get_created_by": {"_include_fields": ("author_profile", "id")},
            "usr_dus_get_author_profile": {
                "_include_fields": [
                    "id",
                    "first_name",
                    "last_name",
                    "profile_image",
                ]
            },
            "doc_duds_get_hubs": {
                "_include_fields": [
                    "id",
                    "name",
                    "namespace",
                    "slug",
                    "created_date",
                ]
            },
            "doc_duds_get_fundraise": {
                "_include_fields": [
                    "id",
                    "status",
                    "goal_amount",
                    "goal_currency",
                    "start_date",
                    "end_date",
                    "amount_raised",
                    "contributors",
                ]
            },
            "doc_duds_get_grant": {
                "_include_fields": [
                    "id",
                    "status",
                    "amount",
                    "currency",
                    "organization",
                    "description",
                    "start_date",
                    "end_date",
                    "created_by",
                    "contacts",
                    "applications",
                    "application_visibility",
                ]
            },
            "pch_dfs_get_contributors": {
                "_include_fields": [
                    "id",
                    "author_profile",
                    "first_name",
                    "last_name",
                ]
            },
            "pch_dgs_get_created_by": {
                "_include_fields": [
                    "id",
                    "author_profile",
                    "first_name",
                    "last_name",
                ]
            },
            "pch_dgs_get_contacts": {
                "_include_fields": [
                    "id",
                    "author_profile",
                    "first_name",
                    "last_name",
                ]
            },
        }

        return metadata_context

    @action(detail=True, methods=["get"], permission_classes=[AllowAny])
    def get_document_metadata(self, request, pk=None):
        unified_document = get_object_or_404(ResearchhubUnifiedDocument, pk=pk)
        # A share token admits only the document it was issued for.
        is_visible = (
            unified_document.is_visible_to_user(request.user)
            or get_shared_unified_document_id(request) == unified_document.id
        )
        if not is_visible:
            return Response(status=status.HTTP_403_FORBIDDEN)
        metadata_context = self._get_document_metadata_context()

        serializer = self.dynamic_serializer_class(
            unified_document,
            _include_fields=(
                "id",
                "documents",
                "reviews",
                "score",
                "hubs",
                "fundraise",
                "grant",
            ),
            context=metadata_context,
        )
        serializer_data = serializer.data

        return Response(serializer_data, status=status.HTTP_200_OK)


def _get_user_votes(created_by, doc_ids, reaction_content_type):
    return Vote.objects.filter(
        content_type=reaction_content_type, object_id__in=doc_ids, created_by=created_by
    )
