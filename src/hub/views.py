from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Count, F, Q
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import (
    AllowAny,
    IsAuthenticated,
    IsAuthenticatedOrReadOnly,
)
from rest_framework.response import Response

from mailing_list.models import EmailRecipient, HubSubscription
from paper.models import Paper
from paper.utils import get_cache_key
from reputation.models import Contribution
from researchhub_access_group.constants import (
    ASSISTANT_EDITOR,
    ASSOCIATE_EDITOR,
    SENIOR_EDITOR,
)
from researchhub_access_group.models import Permission
from researchhub_document.models import ResearchhubUnifiedDocument
from user.models import User
from user.views.follow_view_mixins import FollowViewActionMixin
from utils.http import DELETE, GET, PATCH, POST, PUT
from utils.message import send_email_message
from utils.permissions import CreateOrUpdateIfAllowed
from utils.throttles import THROTTLE_CLASSES

from .filters import HubFilter
from .models import Hub, HubCategory
from .permissions import (
    CensorHub,
    CreateHub,
    IsModeratorOrSuperEditor,
    IsNotSubscribed,
    IsSubscribed,
    UpdateHub,
)
from .serializers import HubCategorySerializer, HubContributionSerializer, HubSerializer


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

    @action(detail=True, methods=[PUT, PATCH, DELETE], permission_classes=[CensorHub])
    def censor(self, request, pk=None):
        hub = self.get_object()

        # Find unified documents with no other hubs
        unified_documents = (
            ResearchhubUnifiedDocument.objects.annotate(
                cnt=Count("hubs", filter=Q(hubs__is_removed=False))
            )
            .filter(cnt__lte=1, hubs__id=hub.id)
            .values_list("id", flat=True)
        )

        # Remove papers of unified documents with no other hubs
        papers = Paper.objects.filter(unified_document__in=unified_documents)
        papers.update(is_removed=True)

        # Update Hub
        hub.is_removed = True

        hub.save(update_fields=["is_removed", "paper_count", "discussion_count"])

        return Response(self.get_serializer(instance=hub).data, status=200)

    @action(
        detail=False,
        methods=[GET],
        permission_classes=[AllowAny],
    )
    def rep_hubs(self, request):
        cache_key = f"rep-hubs"
        cache_hit = cache.get(cache_key)

        if cache_hit:
            return Response(cache_hit, 200)

        rep_hubs = Hub.objects.filter(is_used_for_rep=True)
        serializer = self.get_serializer(rep_hubs, many=True)
        cache.set(cache_key, serializer.data, timeout=3600)

        return Response(serializer.data)

    @action(
        detail=True,
        methods=[GET],
        permission_classes=[IsAuthenticated],
    )
    def check_subscribed(self, request, pk=None):
        hub = self.get_object()
        user_is_subscribed = hub.subscribers.filter(id=request.user.id).exists()
        return Response({"is_subscribed": user_is_subscribed})

    @action(
        detail=True,
        methods=[POST, PUT, PATCH],
        permission_classes=[IsAuthenticated & IsNotSubscribed],
    )
    def subscribe(self, request, pk=None):
        hub = self.get_object()
        try:
            hub.subscribers.add(request.user)
            hub.subscriber_count = hub.get_subscribers_count()
            hub.save(update_fields=["subscriber_count"])

            if hub.is_locked and (len(hub.subscribers.all()) > Hub.UNLOCK_AFTER):
                hub.unlock()

            return self._get_hub_serialized_response(hub, 200)
        except Exception as e:
            return Response(str(e), status=400)

    @action(detail=True, methods=[POST, PUT, PATCH], permission_classes=[IsSubscribed])
    def unsubscribe(self, request, pk=None):
        hub = self.get_object()
        try:
            hub.subscribers.remove(request.user)
            hub.subscriber_count = hub.get_subscribers_count()
            hub.save(update_fields=["subscriber_count"])
            return self._get_hub_serialized_response(hub, 200)
        except Exception as e:
            return Response(str(e), status=400)

    def _get_hub_serialized_response(self, hub, status_code):
        serialized = HubSerializer(hub, context=self.get_serializer_context())
        return Response(serialized.data, status=status_code)

    def _is_subscribed(self, user, hub):
        return user in hub.subscribers.all()

    @action(detail=True, methods=[POST])
    def invite_to_hub(self, request, pk=None):
        recipients = request.data.get("emails", [])

        if len(recipients) < 1:
            message = "Field `emails` can not be empty"
            error = ValidationError(message)
            return Response(error.detail, status=400)

        subject = "Researchhub Hub Invitation"
        hub = Hub.objects.filter(is_removed=False).get(id=pk)

        base_url = request.META["HTTP_ORIGIN"]

        emailContext = {
            "hub_name": hub.name.capitalize(),
            "link": base_url + "/hubs/{}/".format(hub.name),
            "opt_out": base_url + "/email/opt-out/",
        }

        subscriber_emails = hub.subscribers.all().values_list("email", flat=True)

        # Don't send to hub subscribers
        if len(subscriber_emails) > 0:
            for recipient in recipients:
                if recipient in subscriber_emails:
                    recipients.remove(recipient)

        result = send_email_message(
            recipients,
            "invite_to_hub_email.txt",
            subject,
            emailContext,
            "invite_to_hub_email.html",
        )

        response = {"email_sent": False, "result": result}
        if len(result["success"]) > 0:
            response = {"email_sent": True, "result": result}

        return Response(response, status=200)

    @action(detail=False, methods=[POST], permission_classes=[IsModeratorOrSuperEditor])
    def create_new_editor(self, request, pk=None):
        try:
            target_user = User.objects.get(email=request.data.get("editor_email"))
            Permission.objects.create(
                access_type=request.data.get("editor_type"),
                content_type=ContentType.objects.get_for_model(Hub),
                object_id=request.data.get("selected_hub_id"),
                user=target_user,
            )

            email_recipient = EmailRecipient.objects.filter(email=target_user.email)
            if email_recipient.exists():
                email_recipient = email_recipient.first()
                subscription = HubSubscription.objects.create(
                    none=False, notification_frequency=10080
                )
                email_recipient.hub_subscription = subscription
                email_recipient.save()
            return Response("OK", status=200)
        except Exception as e:
            return Response(str(e), status=500)

    @action(detail=False, methods=[POST], permission_classes=[IsModeratorOrSuperEditor])
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

            email_recipient = EmailRecipient.objects.filter(email=target_user.email)
            if email_recipient.exists():
                email_recipient = email_recipient.first()
                hub_subscription = email_recipient.hub_subscription
                hub_subscription.delete()

            return Response("OK", status=200)
        except Exception as e:
            return Response(str(e), status=500)

    def _get_latest_actions_context(self):
        context = {
            "usr_das_get_created_by": {
                "_include_fields": [
                    "id",
                    "first_name",
                    "last_name",
                    "author_profile",
                ]
            },
            "usr_dus_get_author_profile": {
                "_include_fields": [
                    "id",
                    "profile_image",
                ]
            },
            "usr_das_get_item": {
                "_include_fields": [
                    "slug",
                    "paper_title",
                    "title",
                    "unified_document",
                    "content_type",
                    "source",
                    "user",
                    "amount",
                    "plain_text",
                ]
            },
            "pch_dps_get_source": {
                "_include_fields": [
                    "id",
                    "slug",
                    "paper_title",
                    "title",
                    "unified_document",
                    "plain_text",
                ]
            },
            "pch_dps_get_user": {
                "_include_fields": ["first_name", "last_name", "author_profile"]
            },
            "pap_dps_get_unified_document": {
                "_include_fields": [
                    "id",
                    "document_type",
                    "slug",
                    "documents",
                ]
            },
            "dis_dts_get_unified_document": {
                "_include_fields": [
                    "id",
                    "document_type",
                    "documents",
                    "slug",
                ]
            },
            "dis_dcs_get_unified_document": {
                "_include_fields": [
                    "id",
                    "document_type",
                    "documents",
                    "slug",
                ]
            },
            "dis_drs_get_unified_document": {
                "_include_fields": [
                    "id",
                    "document_type",
                    "documents",
                    "slug",
                ]
            },
            "doc_dps_get_unified_document": {
                "_include_fields": [
                    "id",
                    "document_type",
                    "documents",
                    "slug",
                ]
            },
            "doc_duds_get_documents": {
                "_include_fields": [
                    "id",
                    "title",
                    "post_title",
                    "slug",
                ]
            },
        }
        return context

    @action(detail=False, methods=[GET], permission_classes=[AllowAny])
    def by_contributions(self, request):
        query_params = request.query_params
        hub_id = query_params.get("hub_id", None)
        start_date = query_params.get("start_date", None)
        end_date = query_params.get("end_date", None)
        order_by = (
            "-total_contribution_count"
            if (request.GET.get("order_by", "desc") == "desc")
            else "total_contribution_count"
        )

        hub_qs = (
            Hub.objects.all().distinct()
            if (hub_id is None)
            else Hub.objects.filter(id=hub_id)
        )
        contributions = Contribution.objects.filter(
            unified_document__is_removed=False,
            created_date__gte=start_date,
            created_date__lte=end_date,
        )
        if hub_id:
            contributions = contributions.filter(unified_document__hubs=hub_id)

        comment_query = contributions.filter(
            contribution_type=Contribution.COMMENTER
        ).values("unified_document")
        submission_query = contributions.filter(
            contribution_type=Contribution.SUBMITTER
        ).values("unified_document")
        support_query = contributions.filter(
            contribution_type=Contribution.SUPPORTER
        ).values("unified_document")

        hub_qs_ranked_by_contribution = (
            hub_qs.prefetch_related("related_documents")
            .annotate(
                comment_count=Count(
                    "id", filter=Q(related_documents__in=comment_query)
                ),
                submission_count=Count(
                    "id", filter=Q(related_documents__in=submission_query)
                ),
                support_count=Count(
                    "id", filter=Q(related_documents__in=support_query)
                ),
            )
            .annotate(
                total_contribution_count=(
                    F("comment_count") + F("submission_count") + F("support_count")
                )
            )
            .order_by(order_by)
        )

        paginator = Paginator(
            hub_qs_ranked_by_contribution,  # qs
            10,  # page size
        )
        curr_page_number = request.GET.get("page") or 1
        curr_pagation = paginator.page(curr_page_number)

        return Response(
            {
                "count": paginator.count,
                "has_more": curr_pagation.has_next(),
                "page": curr_page_number,
                "result": HubContributionSerializer(
                    curr_pagation.object_list,
                    many=True,
                ).data,
            },
            status=200,
        )


class HubCategoryViewSet(viewsets.ModelViewSet):
    queryset = HubCategory.objects.all()
    serializer_class = HubCategorySerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
