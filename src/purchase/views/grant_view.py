from django.core.cache import cache
from django.db import transaction
from django.db.models import Prefetch, Q, Sum
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from ai_peer_review.models import ProposalReview
from feed.views.grant_cache_mixin import GrantCacheMixin
from purchase.models import Grant, GrantApplication
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from purchase.serializers.grant_create_serializer import GrantCreateSerializer
from purchase.serializers.grant_serializer import DynamicGrantSerializer
from purchase.services.grant_service import GrantModerationService
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from user.permissions import IsModerator


class GrantViewSet(viewsets.ModelViewSet):
    queryset = Grant.objects.all()
    serializer_class = DynamicGrantSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        return qs.prefetch_related(
            Prefetch(
                "proposal_reviews",
                queryset=ProposalReview.objects.prefetch_related("key_insight__items"),
            ),
        )

    def dispatch(self, request, *args, **kwargs):
        self.grant_service = kwargs.pop("grant_service", GrantModerationService())
        return super().dispatch(request, *args, **kwargs)

    def get_permissions(self):
        """Moderators only for update/delete; any authenticated user can create/view."""
        if self.action in ["update", "partial_update", "destroy"]:
            return [IsModerator()]
        return super().get_permissions()

    def _invalidate_grant_feed_cache(self):
        GrantCacheMixin.invalidate_grant_feed_cache()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["pch_dgs_get_created_by"] = {
            "_include_fields": (
                "id",
                "author_profile",
                "first_name",
                "last_name",
            )
        }
        context["pch_dgs_get_contacts"] = {
            "_include_fields": (
                "id",
                "author_profile",
                "first_name",
                "last_name",
            )
        }
        context["usr_dus_get_author_profile"] = {
            "_include_fields": (
                "id",
                "first_name",
                "last_name",
                "created_date",
                "updated_date",
                "profile_image",
                "is_verified",
            )
        }
        return context

    def create(self, request, *args, **kwargs):
        """Create a new grant in PENDING status awaiting moderator approval."""
        serializer = GrantCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            validated_data = serializer.validated_data.copy()
            validated_data["created_by"] = request.user
            grant = serializer.create(validated_data)

        self._invalidate_grant_feed_cache()

        context = self.get_serializer_context()
        response_serializer = self.get_serializer(grant, context=context)
        return Response(response_serializer.data, status=201)

    def update(self, request, *args, **kwargs):
        """
        Update a grant. Only moderators and the grant creator can update grants.
        """
        grant = self.get_object()

        # Allow grant creator to update their own grants
        if request.user != grant.created_by and not request.user.moderator:
            return Response({"message": "Permission denied"}, status=403)

        response = super().update(request, *args, **kwargs)
        self._invalidate_grant_feed_cache()
        return response

    def partial_update(self, request, *args, **kwargs):
        """
        Partially update a grant. Only moderators and the grant creator can update grants.
        """
        grant = self.get_object()

        # Allow grant creator to update their own grants
        if request.user != grant.created_by and not request.user.moderator:
            return Response({"message": "Permission denied"}, status=403)

        response = super().partial_update(request, *args, **kwargs)
        self._invalidate_grant_feed_cache()
        return response

    @action(
        methods=["POST"],
        detail=True,
        permission_classes=[IsModerator],
    )
    def approve(self, request, *args, **kwargs):
        grant = self.get_object()

        try:
            self.grant_service.approve_grant(grant, request.user)
        except ValueError as e:
            return Response({"message": str(e)}, status=400)

        return Response(self.get_serializer(grant).data)

    @action(
        methods=["POST"],
        detail=True,
        permission_classes=[IsModerator],
    )
    def decline(self, request, *args, **kwargs):
        grant = self.get_object()
        reason = request.data.get("reason", "")
        reason_choice = request.data.get("reason_choice", "")

        try:
            self.grant_service.decline_grant(grant, request.user, reason, reason_choice)
        except ValueError as e:
            return Response({"message": str(e)}, status=400)

        return Response(self.get_serializer(grant).data)

    @action(
        methods=["GET"],
        detail=False,
        permission_classes=[IsModerator],
    )
    def pending(self, request, *args, **kwargs):
        queryset = (
            Grant.objects.filter(status=Grant.PENDING)
            .select_related(
                "created_by", "created_by__author_profile", "unified_document"
            )
            .prefetch_related("unified_document__posts")
            .order_by("-created_date")
        )

        organization = request.query_params.get("organization")
        if organization:
            queryset = queryset.filter(organization__icontains=organization)

        created_by = request.query_params.get("created_by")
        if created_by:
            queryset = queryset.filter(created_by_id=created_by)

        page = self.paginate_queryset(queryset)
        if page is not None:
            return self.get_paginated_response(
                self.get_serializer(page, many=True).data
            )

        return Response(self.get_serializer(queryset, many=True).data)

    @action(
        methods=["POST"],
        detail=True,
        permission_classes=[IsModerator],
    )
    def close(self, request, *args, **kwargs):
        """
        Close a grant (set status to CLOSED). Only moderators can close grants.
        """
        grant = self.get_object()

        if grant.status == Grant.CLOSED:
            return Response({"message": "Grant is already closed"}, status=400)

        grant.status = Grant.CLOSED
        grant.save()
        self._invalidate_grant_feed_cache()

        context = self.get_serializer_context()
        serializer = self.get_serializer(grant, context=context)
        return Response(serializer.data)

    @action(
        methods=["POST"],
        detail=True,
        permission_classes=[IsModerator],
    )
    def complete(self, request, *args, **kwargs):
        """
        Mark a grant as completed (set status to COMPLETED). Only moderators can complete grants.
        """
        grant = self.get_object()

        if grant.status == Grant.COMPLETED:
            return Response({"message": "Grant is already completed"}, status=400)

        grant.status = Grant.COMPLETED
        grant.save()
        self._invalidate_grant_feed_cache()

        context = self.get_serializer_context()
        serializer = self.get_serializer(grant, context=context)
        return Response(serializer.data)

    @action(
        methods=["POST"],
        detail=True,
        permission_classes=[IsModerator],
    )
    def reopen(self, request, *args, **kwargs):
        """
        Reopen a grant (set status to OPEN). Only moderators can reopen grants.
        """
        grant = self.get_object()

        if grant.status == Grant.OPEN:
            return Response({"message": "Grant is already open"}, status=400)

        grant.status = Grant.OPEN
        grant.save()
        self._invalidate_grant_feed_cache()

        context = self.get_serializer_context()
        serializer = self.get_serializer(grant, context=context)
        return Response(serializer.data)

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated])
    def application(self, request, pk=None):
        """Apply to a grant with a preregistration post."""
        grant = self.get_object()
        preregistration_post_id = request.data.get("preregistration_post_id")

        # Validation
        try:
            post = ResearchhubPost.objects.get(
                id=preregistration_post_id,
                created_by=request.user,
                document_type=PREREGISTRATION,
            )
        except ResearchhubPost.DoesNotExist:
            return Response({"error": "Invalid preregistration post"}, status=400)

        # Check if grant is still active
        if not grant.is_active():
            return Response(
                {"error": "Grant is no longer accepting applications"}, status=400
            )

        # Create application
        _, created = GrantApplication.objects.get_or_create(
            grant=grant, preregistration_post=post, applicant=request.user
        )

        if created:
            self._invalidate_grant_feed_cache()
            return Response({"message": "Application submitted"}, status=201)
        else:
            return Response({"message": "Already applied"}, status=200)

    @action(detail=False, methods=["get"], permission_classes=[AllowAny])
    def available_funding(self, request, *args, **kwargs):
        cache_key = "grant_available_funding"
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)

        now = timezone.now()
        active_filter = Q(status=Grant.OPEN) & (
            Q(end_date__isnull=True) | Q(end_date__gt=now)
        )
        total_usd = float(
            Grant.objects.filter(active_filter).aggregate(total=Sum("amount"))["total"]
            or 0
        )
        total_rsc = float(RscExchangeRate.usd_to_rsc(total_usd))
        data = {
            "available_funding_in_rsc": round(total_rsc, 2),
            "available_funding_in_usd": round(total_usd, 2),
        }
        cache.set(cache_key, data, timeout=60 * 60 * 12)
        return Response(data)
