from datetime import timedelta

from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Count, F, Q
from django.utils import timezone
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

from discussion.reaction_models import Vote
from hub.filters import HubFilter
from hub.models import Hub, HubCategory
from hub.permissions import (
    CensorHub,
    CreateHub,
    IsModeratorOrSuperEditor,
    IsNotSubscribed,
    IsSubscribed,
    UpdateHub,
)
from hub.serializers import (
    HubCategorySerializer,
    HubContributionSerializer,
    HubSerializer,
)
from mailing_list.models import EmailRecipient, HubSubscription
from paper.models import Paper
from paper.utils import get_cache_key
from reputation.models import Contribution
from researchhub_access_group.constants import EDITOR
from researchhub_access_group.models import Permission
from researchhub_document.utils import reset_unified_document_cache
from user.models import User
from utils.http import DELETE, GET, PATCH, POST, PUT
from utils.message import send_email_message
from utils.permissions import CreateOrUpdateIfAllowed
from utils.throttles import THROTTLE_CLASSES


class CustomPageLimitPagination(PageNumberPagination):
    page_size_query_param = "page_limit"
    max_page_size = 10000


class HubViewSet(viewsets.ModelViewSet):
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
    filter_class = HubFilter
    search_fields = "name"

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

    def dispatch(self, request, *args, **kwargs):
        query_params = request.META.get("QUERY_STRING", "")
        if "score" in query_params:
            cache_key = get_cache_key("hubs", "trending")
            cache_hit = cache.get(cache_key)
            if cache_hit:
                return cache_hit
            else:
                response = super().dispatch(request, *args, **kwargs)
                response.render()
                cache.set(cache_key, response, timeout=60 * 60 * 24 * 7)
                return response
        else:
            response = super().dispatch(request, *args, **kwargs)
        return response

    def get_queryset(self):
        ordering = self.request.query_params.get("ordering", "")
        return self.get_ordered_queryset(ordering)

    # TODO: re consider approach
    def get_ordered_queryset(self, ordering):
        if "score" in ordering:
            two_weeks_ago = timezone.now().date() - timedelta(days=14)
            num_upvotes = Count(
                "papers__votes__vote_type",
                filter=Q(
                    papers__votes__vote_type=Vote.UPVOTE,
                    papers__votes__created_date__gte=two_weeks_ago,
                ),
            )
            num_downvotes = Count(
                "papers__votes__vote_type",
                filter=Q(
                    papers__votes__vote_type=Vote.DOWNVOTE,
                    papers__votes__created_date__gte=two_weeks_ago,
                ),
            )
            paper_count = Count(
                "papers",
                filter=Q(
                    papers__created_date__gte=two_weeks_ago,
                    papers__uploaded_by__isnull=False,
                ),
            )
            score = num_upvotes - num_downvotes
            score += paper_count
            qs = self.queryset.annotate(
                score=score,
            ).order_by("-score")
            return qs
        else:
            return self.queryset

    @action(detail=True, methods=[PUT, PATCH, DELETE], permission_classes=[CensorHub])
    def censor(self, request, pk=None):
        hub = self.get_object()

        # Remove Papers with no other hubs
        Paper.objects.annotate(
            cnt=Count("hubs", filter=Q(hubs__is_removed=False))
        ).filter(cnt__lte=1, hubs__id=hub.id).update(is_removed=True)

        # Update Hub
        hub.is_removed = True

        hub.paper_count = hub.get_paper_count()
        hub.discussion_count = hub.get_discussion_count()

        hub.save(update_fields=["is_removed", "paper_count", "discussion_count"])
        reset_unified_document_cache(with_default_hub=True)

        return Response(self.get_serializer(instance=hub).data, status=200)

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
                access_type=EDITOR,
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
                access_type=EDITOR,
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
            "hyp_dhs_get_unified_document": {
                "_include_fields": [
                    "id",
                    "renderable_text",
                    "title",
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
