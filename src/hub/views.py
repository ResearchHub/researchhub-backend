from django.core.cache import cache
from django.db.models import Count, Q
from django_filters.rest_framework import DjangoFilterBackend
from datetime import timedelta
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.permissions import (
    IsAuthenticated,
    IsAuthenticatedOrReadOnly
)
from rest_framework.response import Response

from .models import Hub, HubCategory
from .permissions import CreateHub, IsSubscribed, IsNotSubscribed, CensorHub
from .serializers import HubSerializer, HubCategorySerializer
from .filters import HubFilter
from user.models import Action
from user.serializers import UserActions
from utils.http import PATCH, POST, PUT, GET, DELETE
from utils.message import send_email_message
from utils.permissions import CreateOrUpdateIfAllowed
from utils.throttles import THROTTLE_CLASSES
from paper.models import Vote, Paper
from paper.utils import get_cache_key, reset_cache


class CustomPageLimitPagination(PageNumberPagination):
    page_size_query_param = 'page_limit'
    max_page_size = 10000


class HubViewSet(viewsets.ModelViewSet):
    queryset = Hub.objects.filter(is_removed=False)
    serializer_class = HubSerializer
    filter_backends = (SearchFilter, DjangoFilterBackend, OrderingFilter,)
    permission_classes = [
        IsAuthenticatedOrReadOnly
        & CreateHub
        & CreateOrUpdateIfAllowed
    ]
    pagination_class = CustomPageLimitPagination
    throttle_classes = THROTTLE_CLASSES
    filter_class = HubFilter
    search_fields = ('name')

    def dispatch(self, request, *args, **kwargs):
        query_params = request.META.get('QUERY_STRING', '')
        if 'score' in query_params:
            cache_key = get_cache_key('hubs', 'trending')
            cache_hit = cache.get(cache_key)
            if cache_hit:
                return cache_hit
            else:
                response = super().dispatch(request, *args, **kwargs)
                response.render()
                cache.set(cache_key, response, timeout=60*60*24*7)
                return response
        else:
            response = super().dispatch(request, *args, **kwargs)
        return response

    def get_queryset(self):
        if 'score' in self.request.query_params.get('ordering', ''):
            two_weeks_ago = timezone.now().date() - timedelta(days=14)
            num_upvotes = Count(
                'papers__vote__vote_type',
                filter=Q(
                    papers__vote__vote_type=Vote.UPVOTE,
                    papers__vote__created_date__gte=two_weeks_ago
                )
            )
            num_downvotes = Count(
                'papers__vote__vote_type',
                filter=Q(
                    papers__vote__vote_type=Vote.DOWNVOTE,
                    papers__vote__created_date__gte=two_weeks_ago
                )
            )
            # TODO: figure out bug with actions_past_two_weeks filter
            # actions_past_two_weeks = Count(
            #     'actions',
            #     filter=Q(
            #         actions__created_date__gte=two_weeks_ago,
            #         actions__user__isnull=False
            #     )
            # )
            paper_count = Count(
                'papers',
                filter=Q(
                    papers__uploaded_date__gte=two_weeks_ago,
                    papers__uploaded_by__isnull=False
                )
            )
            score = num_upvotes - num_downvotes
            score += paper_count
            qs = self.queryset.annotate(
                score=score,
            ).order_by('-score')
            return qs
        else:
            return self.queryset

    @action(
        detail=True,
        methods=[PUT, PATCH, DELETE],
        permission_classes=[CensorHub]
    )
    def censor(self, request, pk=None):
        hub = self.get_object()

        # Remove Papers with no other hubs
        Paper.objects.annotate(cnt=Count('hubs', filter=Q(hubs__is_removed=False))).filter(cnt__lte=1, hubs__id=hub.id).update(is_removed=True)

        # Update Hub
        hub.is_removed = True

        hub.paper_count = hub.get_paper_count()
        hub.discussion_count = hub.get_discussion_count()

        hub.save(update_fields=['is_removed', 'paper_count', 'discussion_count'])
        reset_cache([0])

        return Response(
            self.get_serializer(instance=hub).data,
            status=200
        )

    @action(
        detail=True,
        methods=[POST, PUT, PATCH],
        permission_classes=[IsAuthenticated & IsNotSubscribed]
    )
    def subscribe(self, request, pk=None):
        hub = self.get_object()
        try:
            hub.subscribers.add(request.user)
            hub.subscriber_count = hub.get_subscriber_count()
            hub.save(update_fields=['subscriber_count'])

            if hub.is_locked and (
                len(hub.subscribers.all()) > Hub.UNLOCK_AFTER
            ):
                hub.unlock()

            return self._get_hub_serialized_response(hub, 200)
        except Exception as e:
            return Response(str(e), status=400)

    @action(
        detail=True,
        methods=[POST, PUT, PATCH],
        permission_classes=[IsSubscribed]
    )
    def unsubscribe(self, request, pk=None):
        hub = self.get_object()
        try:
            hub.subscribers.remove(request.user)
            hub.subscriber_count = hub.get_subscriber_count()
            hub.save(update_fields=['subscriber_count'])
            return self._get_hub_serialized_response(hub, 200)
        except Exception as e:
            return Response(str(e), status=400)

    def _get_hub_serialized_response(self, hub, status_code):
        serialized = HubSerializer(hub, context=self.get_serializer_context())
        return Response(serialized.data, status=status_code)

    def _is_subscribed(self, user, hub):
        return user in hub.subscribers.all()

    @action(
        detail=True,
        methods=[POST]
    )
    def invite_to_hub(self, request, pk=None):
        recipients = request.data.get('emails', [])

        if len(recipients) < 1:
            message = 'Field `emails` can not be empty'
            error = ValidationError(message)
            return Response(error.detail, status=400)

        subject = 'Researchhub Hub Invitation'
        hub = Hub.objects.filter(is_removed=False).get(id=pk)

        base_url = request.META['HTTP_ORIGIN']

        emailContext = {
            'hub_name': hub.name.capitalize(),
            'link': base_url + '/hubs/{}/'.format(hub.name),
            'opt_out': base_url + '/email/opt-out/'
        }

        subscriber_emails = hub.subscribers.all().values_list(
            'email',
            flat=True
        )

        # Don't send to hub subscribers
        if len(subscriber_emails) > 0:
            for recipient in recipients:
                if recipient in subscriber_emails:
                    recipients.remove(recipient)

        result = send_email_message(
            recipients,
            'invite_to_hub_email.txt',
            subject,
            emailContext,
            'invite_to_hub_email.html'
        )

        response = {'email_sent': False, 'result': result}
        if len(result['success']) > 0:
            response = {'email_sent': True, 'result': result}

        return Response(response, status=200)

    @action(
        detail=True,
        methods=[GET]
    )
    def latest_actions(self, request, pk=None):
        models = [
            'bulletpoint',
            'thread',
            'comment',
            'reply',
            'summary',
            'purchase'
        ]

        # PK == 0 indicates for now that we're on the homepage
        if pk == '0':
            actions = Action.objects.prefetch_related('item')
        else:
            actions = Action.objects.filter(
                hubs=pk
            ).prefetch_related('item')

        actions = actions.filter(
            user__isnull=False,
            user__is_suspended=False,
            user__probable_spammer=False,
            content_type__model__in=models+['paper'],
            display=True
        ).order_by('-created_date')

        # actions = actions.filter(
        #     (
        #         Q(papers__is_removed=False) |
        #         Q(bullet_point__paper__is_removed=False) |
        #         Q(threads__paper__is_removed=False) |
        #         Q(summaries__paper__is_removed=False) |
        #         Q(comments__parent__paper__is_removed=False)
        #         # Q(replies__parent__parent__paper__is_removed=False)
        #     )
        # ).order_by('-created_date')

        page = self.paginate_queryset(actions)
        if page is not None:
            data = UserActions(data=page, user=request.user).serialized
            return self.get_paginated_response(data)

        data = UserActions(data=actions, user=request.user).serialized
        return Response(data)


class HubCategoryViewSet(viewsets.ModelViewSet):
    queryset = HubCategory.objects.all()
    serializer_class = HubCategorySerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
