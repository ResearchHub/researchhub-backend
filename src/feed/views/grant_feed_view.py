from django.db.models import Case, DecimalField, Exists, IntegerField, OuterRef, Prefetch, Q, Sum, Value, When
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework import serializers
from rest_framework.viewsets import ModelViewSet

from feed.views.feed_view_mixin import FeedViewMixin
from purchase.related_models.grant_application_model import GrantApplication
from purchase.related_models.grant_model import Grant
from researchhub_document.related_models.constants.document_type import GRANT
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost

from .common import FeedPagination


class GrantFeedViewSet(FeedViewMixin, ModelViewSet):
    permission_classes = []
    pagination_class = FeedPagination
    ordering = "-created_date"

    def get_serializer_class(self):
        return serializers.Serializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context.update(self.get_common_serializer_context())
        return context

    def get_cache_key(self, request, feed_type=""):
        base_key = super().get_cache_key(request, feed_type)
        status = request.query_params.get("status", "")
        organization = request.query_params.get("organization", "")
        return f"{base_key}:{status}:{organization}"

    def list(self, request, *args, **kwargs):
        page_num = int(request.query_params.get("page", "1"))
        status = request.query_params.get("status")
        organization = request.query_params.get("organization")
        sort_by = request.query_params.get("sort_by")
        cache_key = self.get_cache_key(request, "grants")
        
        cacheable_sorts = {None, "hot_score", "upvotes", "amount_raised"}
        cacheable_statuses = {None, "OPEN", "CLOSED"}
        use_cache = (
            page_num <= 4
            and organization is None
            and sort_by in cacheable_sorts
            and (status.upper() if status else None) in cacheable_statuses
        )
        
        return self._list_fund_entries(request, cache_key, use_cache)

    def get_queryset(self):
        status = self.request.query_params.get("status")
        organization = self.request.query_params.get("organization")
        sort_by = self.request.query_params.get("sort_by")

        queryset = self._build_base_queryset()
        
        if status and status.upper() in [Grant.OPEN, Grant.CLOSED, Grant.COMPLETED]:
            queryset = queryset.filter(unified_document__grants__status=status.upper())
        
        if organization:
            queryset = queryset.filter(unified_document__grants__organization__icontains=organization)
        
        if sort_by == "amount_raised":
            queryset = queryset.annotate(
                grant_amount=Coalesce(
                    Sum("unified_document__grants__amount"), 0, output_field=DecimalField()
                )
            ).order_by("status_priority", "-grant_amount", "id")
        elif sort_by == "hot_score":
            queryset = queryset.order_by("status_priority", "-unified_document__hot_score", "id")
        elif sort_by == "upvotes":
            queryset = queryset.order_by("status_priority", "-score", "id")
        else:
            queryset = queryset.order_by("status_priority", "-created_date", "id")
        
        return queryset

    def _build_base_queryset(self):
        now = timezone.now()
        
        has_active = Grant.objects.filter(
            unified_document_id=OuterRef("unified_document_id"),
            status=Grant.OPEN
        ).filter(
            Q(end_date__isnull=True) | Q(end_date__gt=now)
        ).values('pk')[:1]
        
        grant_prefetch = Prefetch(
            "unified_document__grants",
            queryset=Grant.objects.select_related(
                "created_by__author_profile__user"
            ).prefetch_related(
                Prefetch(
                    "applications",
                    queryset=GrantApplication.objects.select_related(
                        "applicant__author_profile__user"
                    ).order_by("created_date")
                )
            ).annotate(
                is_expired_flag=Case(
                    When(end_date__lt=now, then=Value(True)),
                    default=Value(False),
                    output_field=IntegerField()
                ),
                is_active_flag=Case(
                    When(
                        Q(status=Grant.OPEN) & (Q(end_date__isnull=True) | Q(end_date__gte=now)),
                        then=Value(True)
                    ),
                    default=Value(False),
                    output_field=IntegerField()
                )
            ).order_by("end_date")
        )
        
        return ResearchhubPost.objects.select_related(
            "created_by__author_profile__user",
            "unified_document"
        ).prefetch_related(
            "unified_document__hubs",
            grant_prefetch
        ).filter(
            document_type=GRANT,
            unified_document__is_removed=False
        ).annotate(
            status_priority=Case(
                When(Exists(has_active), then=Value(0)),
                default=Value(1),
                output_field=IntegerField()
            )
        )