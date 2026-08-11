from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import action
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
from researchhub_document.services.unified_document_share_link_service import (
    UnifiedDocumentShareLinkService,
    get_shared_unified_document_id,
)
from utils.permissions import ReadOnly


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
                    "is_used_for_rep",
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
    def share_link(self, request, pk=None):
        """Return the proposal's share link, generating one when needed.

        Regenerates an expired link, so callers must only hit this on an
        explicit user action and never on page render.
        """
        # Screened here so a malformed id answers 404 rather than falling
        # through to the ValueError branch reserved for rejected requests.
        if pk is None or not str(pk).isdigit():
            return Response(status=status.HTTP_404_NOT_FOUND)

        try:
            link, created = UnifiedDocumentShareLinkService().create_or_get(
                pk, request.user
            )
        except ResearchhubUnifiedDocument.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        except PermissionError as error:
            return Response({"detail": str(error)}, status=status.HTTP_403_FORBIDDEN)
        except ValueError as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            UnifiedDocumentShareLinkSerializer(link).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @share_link.mapping.delete
    def disable_share_link(self, request, pk=None):
        """Turn sharing off, invalidating any link already handed out.

        Idempotent: answers 204 whether or not a link existed, so a toggle can
        call it without first checking.
        """
        if pk is None or not str(pk).isdigit():
            return Response(status=status.HTTP_404_NOT_FOUND)

        try:
            UnifiedDocumentShareLinkService().disable(pk, request.user)
        except ResearchhubUnifiedDocument.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        except PermissionError as error:
            return Response({"detail": str(error)}, status=status.HTTP_403_FORBIDDEN)
        except ValueError as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(status=status.HTTP_204_NO_CONTENT)

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
                    "is_used_for_rep",
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
