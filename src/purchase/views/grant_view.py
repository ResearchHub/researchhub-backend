import logging

from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from feed.models import FeedEntry
from feed.tasks import create_feed_entry
from feed.views.grant_feed_view import GRANT_FEED_CACHE_VERSION_KEY
from notification.models import Notification
from purchase.models import Grant, GrantApplication
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from purchase.serializers.grant_create_serializer import GrantCreateSerializer
from purchase.serializers.grant_serializer import DynamicGrantSerializer
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from user.permissions import IsModerator
from utils.doi import DOI

logger = logging.getLogger(__name__)


class GrantViewSet(viewsets.ModelViewSet):
    queryset = Grant.objects.all()
    serializer_class = DynamicGrantSerializer
    permission_classes = [IsAuthenticated]

    def get_permissions(self):
        """
        Only moderators can update or delete grants.
        Any authenticated user can create or view grants.
        """
        if self.action in ["update", "partial_update", "destroy"]:
            return [IsModerator()]
        return super().get_permissions()

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
        context["pch_dgs_get_reviewed_by"] = {
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
        """
        Create a new grant. The grant starts in PENDING status and
        requires moderator approval to become OPEN.
        """
        serializer = GrantCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            validated_data = serializer.validated_data.copy()
            validated_data["created_by"] = request.user
            grant = serializer.create(validated_data)

        context = self.get_serializer_context()
        response_serializer = self.get_serializer(grant, context=context)
        return Response(response_serializer.data, status=201)

    def update(self, request, *args, **kwargs):
        """
        Update a grant. Only moderators and the grant creator can update grants.
        """
        grant = self.get_object()

        # Allow grant creator to update their own grants
        if request.user != grant.created_by and not request.user.is_moderator():
            return Response({"message": "Permission denied"}, status=403)

        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        """
        Partially update a grant. Only moderators and the grant creator can update grants.
        """
        grant = self.get_object()

        # Allow grant creator to update their own grants
        if request.user != grant.created_by and not request.user.is_moderator():
            return Response({"message": "Permission denied"}, status=403)

        return super().partial_update(request, *args, **kwargs)

    @action(
        methods=["POST"],
        detail=True,
        permission_classes=[IsModerator],
    )
    def approve(self, request, *args, **kwargs):
        grant = self.get_object()

        if grant.status != Grant.PENDING:
            return Response(
                {"message": "Only pending grants can be approved"}, status=400
            )

        grant.status = Grant.OPEN
        grant.reviewed_by = request.user
        grant.reviewed_date = timezone.now()
        grant.save(update_fields=["status", "reviewed_by", "reviewed_date"])

        cache.delete("grant_available_funding")
        cache.set(GRANT_FEED_CACHE_VERSION_KEY, int(timezone.now().timestamp()))

        post = grant.unified_document.posts.first()
        self._assign_doi_to_post(post)
        self._create_feed_entry_for_post(post)
        self._send_moderation_notification(
            grant, request.user, Notification.GRANT_APPROVED
        )

        return Response(self.get_serializer(grant).data)

    @action(
        methods=["POST"],
        detail=True,
        permission_classes=[IsModerator],
    )
    def decline(self, request, *args, **kwargs):
        grant = self.get_object()

        if grant.status != Grant.PENDING:
            return Response(
                {"message": "Only pending grants can be declined"}, status=400
            )

        grant.status = Grant.DECLINED
        grant.reviewed_by = request.user
        grant.reviewed_date = timezone.now()
        grant.decline_reason = request.data.get("reason", "")
        grant.save(
            update_fields=[
                "status",
                "reviewed_by",
                "reviewed_date",
                "decline_reason",
            ]
        )

        unified_document = grant.unified_document
        unified_document.is_removed = True
        unified_document.save(update_fields=["is_removed"])

        cache.set(GRANT_FEED_CACHE_VERSION_KEY, int(timezone.now().timestamp()))

        self._send_moderation_notification(
            grant, request.user, Notification.GRANT_DECLINED
        )

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

    def _assign_doi_to_post(self, post):
        if not post or post.doi:
            return

        try:
            doi = DOI()
            post.doi = doi.doi
            post.save(update_fields=["doi"])

            author = post.created_by.author_profile
            doi.register_doi_for_post([author], post.title, post)
        except Exception:
            logger.exception("Failed to assign DOI to post %s", post.id)

    def _create_feed_entry_for_post(self, post):
        if not post:
            return

        try:
            hub_ids = list(
                post.unified_document.hubs.values_list("id", flat=True)
            )
            content_type_id = ContentType.objects.get_for_model(post).id

            transaction.on_commit(
                lambda: create_feed_entry.apply_async(
                    args=(
                        post.id,
                        content_type_id,
                        FeedEntry.PUBLISH,
                        hub_ids,
                        post.created_by_id,
                    ),
                    priority=1,
                )
            )
        except Exception:
            logger.exception("Failed to create feed entry for post %s", post.id)

    def _send_moderation_notification(self, grant, action_user, notification_type):
        try:
            content_type = ContentType.objects.get_for_model(Grant)
            notification = Notification.objects.create(
                notification_type=notification_type,
                recipient=grant.created_by,
                action_user=action_user,
                content_type=content_type,
                object_id=grant.id,
                unified_document=grant.unified_document,
            )
            notification.send_notification()
        except Exception:
            logger.exception(
                "Failed to send %s notification for grant %s",
                notification_type,
                grant.id,
            )
