from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.db.models import Q
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import (
    AllowAny,
    IsAuthenticatedOrReadOnly,
)
from rest_framework.response import Response

from hub.mappers.arxiv_mappings import ARXIV_MAPPINGS
from hub.mappers.biorxiv_mappings import BIORXIV_MAPPINGS
from hub.mappers.chemrxiv_mappings import CHEMRXIV_MAPPINGS
from hub.mappers.medrxiv_mappings import MEDRXIV_MAPPINGS
from paper.utils import get_cache_key
from researchhub_access_group.constants import (
    ASSISTANT_EDITOR,
    ASSOCIATE_EDITOR,
    SENIOR_EDITOR,
)
from researchhub_access_group.models import Permission
from user.models import User
from user.views.follow_view_mixins import FollowViewActionMixin
from utils.permissions import CreateOrUpdateIfAllowed
from utils.throttles import THROTTLE_CLASSES

from .filters import HubFilter
from .models import Hub
from .permissions import (
    CreateHub,
    IsModeratorOrSuperEditor,
    UpdateHub,
)
from .serializers import HubSerializer


class CustomPageLimitPagination(PageNumberPagination):
    page_size_query_param = "page_limit"
    max_page_size = 100
    page_size = 40


class HubViewSet(viewsets.ModelViewSet, FollowViewActionMixin):
    queryset = Hub.objects.filter(is_removed=False)
    serializer_class = HubSerializer
    filter_backends = (
        SearchFilter,
        DjangoFilterBackend,
        OrderingFilter,
    )
    permission_classes = [
        IsAuthenticatedOrReadOnly & CreateHub & CreateOrUpdateIfAllowed & UpdateHub
    ]
    pagination_class = CustomPageLimitPagination
    throttle_classes = THROTTLE_CLASSES
    filterset_class = HubFilter
    search_fields = "name"

    def get_queryset(self):
        queryset = super().get_queryset()
        exclude_journals = (
            self.request.query_params.get("exclude_journals", "").lower() == "true"
        )
        if exclude_journals:
            queryset = queryset.exclude(namespace="journal")
        return queryset

    def get_serializer_context(self):
        return {
            **super().get_serializer_context(),
            "rag_dps_get_user": {
                "_include_fields": [
                    "author_profile",
                    "email",
                    "id",
                ]
            },
            "hub_shs_get_editor_permission_groups": {"_exclude_fields": ("source",)},
        }

    def list(self, request):
        page = request.query_params.get("page", 1)
        ordering = request.query_params.get("ordering", None)

        # only cache the first page of trending hubs,
        # since it's the most frequently queried
        if ordering == "-paper_count,-discussion_count,id" and page == 1:
            cache_key = get_cache_key("hubs", "trending")
            cache_hit = cache.get(cache_key)

            if cache_hit:
                return Response(cache_hit)
            else:
                response = super().list(request)
                data = response.data
                cache.set(cache_key, data, timeout=60 * 60 * 24 * 7)
                return Response(data)
        else:
            return super().list(request)

    def create(self, request):
        response = super().create(request)
        cache_key = get_cache_key("hubs", "trending")
        cache.delete(cache_key)
        return response

    @action(
        detail=False,
        methods=["POST"],
        permission_classes=[IsModeratorOrSuperEditor],
    )
    def create_new_editor(self, request, pk=None):
        try:
            target_user = User.objects.get(email=request.data.get("editor_email"))
            Permission.objects.create(
                access_type=request.data.get("editor_type"),
                content_type=ContentType.objects.get_for_model(Hub),
                object_id=request.data.get("selected_hub_id"),
                user=target_user,
            )

            return Response("OK", status=200)
        except Exception as e:
            return Response(str(e), status=500)

    @action(
        detail=False,
        methods=["POST"],
        permission_classes=[IsModeratorOrSuperEditor],
    )
    def delete_editor(self, request, pk=None):
        try:
            target_user = User.objects.get(email=request.data.get("editor_email"))

            target_editors_permissions = Permission.objects.filter(
                (
                    Q(access_type=ASSISTANT_EDITOR)
                    | Q(access_type=ASSOCIATE_EDITOR)
                    | Q(access_type=SENIOR_EDITOR)
                ),
                content_type=ContentType.objects.get_for_model(Hub),
                object_id=request.data.get("selected_hub_id"),
                user=target_user,
            )

            for permission in target_editors_permissions:
                permission.delete()

            return Response("OK", status=200)
        except Exception as e:
            return Response(str(e), status=500)

    @action(detail=False, methods=["GET"], permission_classes=[AllowAny])
    def primary_only(self, request):
        """
        Returns a list of all unique hubs (both categories and subcategories)
        that appear in the mappings, deduplicated, sorted by paper_count descending.
        """

        cache_key = get_cache_key("hubs", "primary_only")
        cached_data = cache.get(cache_key)

        if cached_data:
            return Response(cached_data, status=200)

        # Extract all unique hub slugs (both category and subcategory) from mappings
        all_hub_slugs = set()
        all_mappings = [
            ARXIV_MAPPINGS,
            BIORXIV_MAPPINGS,
            CHEMRXIV_MAPPINGS,
            MEDRXIV_MAPPINGS,
        ]

        for source in all_mappings:
            for category_slug, subcategory_slug in source.values():
                if category_slug:
                    all_hub_slugs.add(category_slug)
                if subcategory_slug:
                    all_hub_slugs.add(subcategory_slug)

        # Get all unique hubs, sorted by paper_count descending
        primary_hubs = Hub.objects.filter(
            slug__in=all_hub_slugs, is_removed=False
        ).order_by("-paper_count")

        # Serialize all results
        serializer = self.get_serializer(primary_hubs, many=True)

        # Return with count and results format
        response_data = {"count": primary_hubs.count(), "results": serializer.data}

        cache.set(cache_key, response_data, timeout=60 * 60 * 24)

        return Response(response_data, status=200)
