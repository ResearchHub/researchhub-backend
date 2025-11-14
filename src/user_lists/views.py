from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError
from django.db.models import Count, Prefetch, Q
from django.utils import timezone
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from feed.models import FeedEntry
from paper.models import Paper
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost 
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from feed.views.common import FeedPagination
from researchhub.permissions import IsObjectOwner

from .models import List, ListItem
from .serializers import (
    ListItemReadSerializer,
    ListItemWriteSerializer,
    ListSerializer,
    OverviewSerializer,
)


class ListViewSet(viewsets.ModelViewSet):
    serializer_class = ListSerializer
    permission_classes = [IsAuthenticated, IsObjectOwner]
    pagination_class = FeedPagination

    def get_queryset(self):
        queryset = List.objects.filter(is_removed=False, created_by=self.request.user).order_by("-updated_date")

        if self.action in ["list", "retrieve"]:
            queryset = queryset.annotate(items_count=Count("items", filter=Q(items__is_removed=False)))

        return queryset

    def perform_create(self, serializer):
        serializer.save(
            created_by=self.request.user,
            updated_by=self.request.user
        )

    def perform_update(self, serializer):
        serializer.save(
            updated_by=self.request.user,
            updated_date=timezone.now()
        )

    def perform_destroy(self, instance):
        instance.is_removed = True 
        instance.updated_date = timezone.now()
        instance.save(update_fields=["is_removed", "updated_date"])

    @action(detail=False, methods=["get"], url_path="overview")
    def overview(self, request):
        lists = List.objects.filter(is_removed=False, created_by=request.user).prefetch_related(
            Prefetch(
                "items",
                queryset=ListItem.objects.filter(is_removed=False).order_by("-created_date"),
                to_attr="overview_items"
            )
        ).order_by("-updated_date")
        serializer = OverviewSerializer(lists, many=True)
        return Response({"lists": serializer.data})


class ListItemViewSet(viewsets.ModelViewSet):
    serializer_class = ListItemReadSerializer
    permission_classes = [IsAuthenticated, IsObjectOwner]
    pagination_class = FeedPagination

    def get_queryset(self): 
        feed_entry_prefetch = Prefetch(
            "unified_document__feed_entries",
            queryset=FeedEntry.objects.select_related("content_type", "user", "user__author_profile"),
            to_attr="cached_feed_entries"
        )
        
        queryset = (
            ListItem.objects.filter(is_removed=False, created_by=self.request.user)
            .select_related("unified_document", "unified_document__paper", "parent_list")
            .prefetch_related(feed_entry_prefetch, "unified_document__posts")
            .order_by("-created_date")
        )

        parent_list_id = self.request.query_params.get("parent_list")
        if parent_list_id:
            queryset = queryset.filter(
                parent_list_id=parent_list_id,
                parent_list__created_by=self.request.user,
                parent_list__is_removed=False,
            )

        return queryset

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.action not in ["create", "update"]:
            context['content_type_cache'] = {
                Paper: ContentType.objects.get_for_model(Paper),
                ResearchhubPost: ContentType.objects.get_for_model(ResearchhubPost),
            }
        return context

    def get_serializer_class(self):
        if self.action in ["create", "update"]:
            return ListItemWriteSerializer
        return ListItemReadSerializer

    def perform_create(self, serializer):
        try:
            item = serializer.save(created_by=self.request.user, updated_by=self.request.user)
            self._update_parent_list_timestamp(item.parent_list)
        except IntegrityError:
            raise serializers.ValidationError({"error": "Item already exists in this list."})

    def perform_update(self, serializer):
        old_parent_list = serializer.instance.parent_list
        try:
            item = serializer.save(updated_by=self.request.user, updated_date=timezone.now())
            self._update_parent_list_timestamp(item.parent_list)
            if old_parent_list.id != item.parent_list.id:
                self._update_parent_list_timestamp(old_parent_list)
        except IntegrityError:
            raise serializers.ValidationError({"error": "Item already exists in this list."})

    def perform_destroy(self, instance):
        parent_list = instance.parent_list
        instance.is_removed = True
        instance.updated_date = timezone.now()
        instance.save(update_fields=["is_removed", "updated_date"])
        self._update_parent_list_timestamp(parent_list)

    def _update_parent_list_timestamp(self, parent_list):
        parent_list.updated_by = self.request.user
        parent_list.updated_date = timezone.now()
        parent_list.save(update_fields=["updated_by", "updated_date"])
