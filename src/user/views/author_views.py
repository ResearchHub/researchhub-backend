from celery import chain
from django.core.cache import cache
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import (
    AllowAny,
    IsAuthenticated,
    IsAuthenticatedOrReadOnly,
)
from rest_framework.response import Response

from paper.openalex_tasks import pull_openalex_author_works_batch
from paper.related_models.authorship_model import Authorship
from researchhub.settings import TESTING
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from researchhub_document.serializers.researchhub_unified_document_serializer import (
    DynamicUnifiedDocumentSerializer,
)
from researchhub_document.views.researchhub_unified_document_views import (
    ResearchhubUnifiedDocumentViewSet,
)
from user.models import Author
from user.permissions import DeleteAuthorPermission, IsVerifiedUser, UpdateAuthor
from user.serializers import (
    AuthorEditableSerializer,
    AuthorSerializer,
    DynamicAuthorProfileSerializer,
)
from user.tasks import invalidate_author_profile_caches
from user.utils import AuthorClaimError, claim_openalex_author_profile
from user.views.follow_view_mixins import FollowViewActionMixin
from utils.permissions import CreateOrUpdateIfAllowed
from utils.throttles import THROTTLE_CLASSES


class AuthorViewSet(viewsets.ModelViewSet, FollowViewActionMixin):
    queryset = Author.objects.select_related(
        "user",
        "user__userverification",
    )
    serializer_class = AuthorSerializer
    filter_backends = (SearchFilter, OrderingFilter)
    search_fields = ("first_name", "last_name")
    permission_classes = [
        (IsAuthenticatedOrReadOnly & UpdateAuthor & CreateOrUpdateIfAllowed)
        | DeleteAuthorPermission
    ]
    throttle_classes = THROTTLE_CLASSES

    def create(self, request, *args, **kwargs):
        """Override to use an editable serializer."""
        serializer = AuthorEditableSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(
            serializer.data, status=status.HTTP_201_CREATED, headers=headers
        )

    def update(self, request, *args, **kwargs):
        """Override to use an editable serializer."""
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = AuthorEditableSerializer(
            instance, data=request.data, partial=partial
        )
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)

        if getattr(instance, "_prefetched_objects_cache", None):
            # If 'prefetch_related' has been applied to a queryset, we need to
            # forcibly invalidate the prefetch cache on the instance.
            instance._prefetched_objects_cache = {}

        return Response(serializer.data)

    @action(detail=True, methods=["get"], permission_classes=[AllowAny])
    def summary_stats(self, request, pk=None):
        author = self.get_object()
        cache_key = f"author-{author.id}-summary-stats"
        cache_hit = cache.get(cache_key)

        if cache_hit:
            return Response(cache_hit, 200)

        serializer = DynamicAuthorProfileSerializer(
            author,
            _include_fields=[
                "summary_stats",
            ],
        )

        cache.set(cache_key, serializer.data, timeout=60 * 60 * 24)

        return Response(serializer.data, status=200)

    @action(detail=True, methods=["get"], permission_classes=[AllowAny])
    def achievements(self, request, pk=None):
        author = self.get_object()
        cache_key = f"author-{author.id}-achievements"
        cache_hit = cache.get(cache_key)

        if cache_hit:
            return Response(cache_hit, 200)

        author = self.get_object()
        serializer = DynamicAuthorProfileSerializer(
            author,
            _include_fields=[
                "achievements",
            ],
        )

        cache.set(cache_key, serializer.data, timeout=60 * 60 * 24)

        return Response(serializer.data, status=200)

    @action(
        detail=True,
        methods=["get"],
    )
    def publications(self, request, pk=None):
        author = self.get_object()

        # Get documents from cache if available
        cache_key = f"author-{author.id}-publications"
        documents = cache.get(cache_key)

        if not documents:
            # Use UNION for better query performance (avoids sequential scan)
            direct = Authorship.objects.filter(author=author)
            merged = Authorship.objects.filter(author__merged_with_author=author)
            all_authorships = direct.union(merged)

            # Get doc IDs and sort by citations (UNION doesn't support order_by)
            authorship_ids = list(all_authorships.values_list("id", flat=True))
            authored_doc_ids = list(
                Authorship.objects.filter(id__in=authorship_ids)
                .order_by("-paper__citations")
                .values_list("paper__unified_document_id", flat=True)
            )

            docs = ResearchhubUnifiedDocument.objects.filter(id__in=authored_doc_ids)

            # Maintain the ordering authored papers
            documents = sorted(docs, key=lambda x: authored_doc_ids.index(x.id))

            cache.set(cache_key, documents, timeout=60 * 60 * 24)

        context = ResearchhubUnifiedDocumentViewSet._get_serializer_context(self)
        page = self.paginate_queryset(documents)

        serializer = DynamicUnifiedDocumentSerializer(
            page,
            _include_fields=[
                "id",
                "created_date",
                "documents",
                "document_filter",
                "document_type",
                "hot_score",
                "hubs",
                "reviews",
                "score",
                "fundraise",
                "grant",
            ],
            many=True,
            context=context,
        )

        serializer_data = serializer.data

        return self.get_paginated_response(serializer_data)

    @action(
        detail=True,
        permission_classes=[IsAuthenticated, IsVerifiedUser],
    )
    @publications.mapping.post
    def add_publications(self, request, pk=None):
        author = request.user.author_profile
        openalex_ids = request.data.get("openalex_ids", [])
        openalex_author_id = request.data.get("openalex_author_id", None)

        # Ensure the openalex author id is a full url since it is the format stored in
        # our system
        if "openalex.org" not in openalex_author_id:
            openalex_author_id = f"https://openalex.org/authors/{openalex_author_id}"

        # Attempt to associate the openalex author id with the RH author
        try:
            claim_openalex_author_profile(author.id, openalex_author_id)
        except AuthorClaimError:
            pass
        except Exception:
            return Response(status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if len(openalex_ids) > 0:
            # if True:
            if TESTING:
                pull_openalex_author_works_batch(openalex_ids, request.user.id)
                invalidate_author_profile_caches(None, author.id)
            else:
                chain(
                    pull_openalex_author_works_batch.s(openalex_ids, request.user.id),
                    invalidate_author_profile_caches.s(author.id),
                ).apply_async(priority=1)

        return Response(status=status.HTTP_200_OK)

    @action(
        detail=True,
        permission_classes=[IsAuthenticated, IsVerifiedUser],
    )
    @publications.mapping.delete
    def delete_publications(self, request, pk=None):
        paper_ids = request.data.get("paper_ids", [])

        authorships = Authorship.objects.filter(
            paper__id__in=paper_ids, author=request.user.author_profile
        )

        count, _ = authorships.delete()
        invalidate_author_profile_caches(None, request.user.author_profile.id)
        return Response({"count": count}, status=status.HTTP_200_OK)

    @action(detail=True, methods=["get"], permission_classes=[AllowAny])
    def minimal_overview(self, request, pk=None):
        author = self.get_object()
        context = {
            "usr_dus_get_author_profile": {
                "_include_fields": (
                    "id",
                    "first_name",
                    "last_name",
                    "university",
                    "facebook",
                    "linkedin",
                    "twitter",
                    "google_scholar",
                    "description",
                    "education",
                    "headline",
                    "profile_image",
                    "is_orcid_connected",
                )
            }
        }
        serializer = AuthorSerializer(
            author,
            context=context,
        )
        return Response(serializer.data, status=200)
