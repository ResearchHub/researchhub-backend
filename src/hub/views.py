from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.permissions import (
    IsAuthenticated,
    IsAuthenticatedOrReadOnly
)
from rest_framework.response import Response

from .models import Hub
from .permissions import CreateHub, IsSubscribed, IsNotSubscribed
from .serializers import HubSerializer
from .filters import *
from paper.models import Paper
from paper.serializers import PaperSerializer
from utils.paginators import *

import datetime

class HubViewSet(viewsets.ModelViewSet):
    queryset = Hub.objects.all()
    serializer_class = HubSerializer
    filter_backends = (SearchFilter, DjangoFilterBackend, OrderingFilter)
    permission_classes = [IsAuthenticatedOrReadOnly & CreateHub]
    filter_class = HubFilter
    search_fields = ('name')

    @action(
        detail=True,
        methods=['post', 'put', 'patch'],
        permission_classes=[IsAuthenticated & IsNotSubscribed]
    )
    def subscribe(self, request, pk=None):
        hub = self.get_object()
        try:
            hub.subscribers.add(request.user)
            hub.save()
            return self._get_hub_serialized_response(hub, 200)
        except Exception as e:
            return Response(e, status=400)

    @action(
        detail=True,
        methods=['post', 'put', 'patch'],
        permission_classes=[IsSubscribed]
    )
    def unsubscribe(self, request, pk=None):
        hub = self.get_object()
        try:
            hub.subscribers.remove(request.user)
            hub.save()
            return self._get_hub_serialized_response(hub, 200)
        except Exception as e:
            return Response(e, status=400)

    def _get_hub_serialized_response(self, hub, status_code):
        serialized = HubSerializer(hub)
        return Response(serialized.data, status=status_code)

    def _is_subscribed(self, user, hub):
        return user in hub.subscribers.all()

    @action(
        detail=True,
        methods=['get'],
    )
    def get_hub_papers(self, request, pk=None):
        def most_discussed_sort(paper):
            discussions = paper.threads.all()
            total_discussed = len(discussion)
            comments = []
            for discussion in discussions:
                total_discussed = total_discussed + discussion.comment.count()
                comments = comments + discussion.comment.all()

            for comment in comments:
                total_discussed = total_discussed + comment.replies.count()

            return total_discussed

        uploaded_start = datetime.datetime.fromtimestamp(int(request.GET["uploaded_date__gte"]))
        uploaded_end = datetime.datetime.fromtimestamp(int(request.GET["uploaded_date__lte"]))
        ordering = request.GET['ordering']

        papers = Paper.objects.filter(
            hubs=pk,
            uploaded_date__gte=uploaded_start,
            uploaded_date__lte=uploaded_end
        )
        order_papers = papers

        if ordering == 'newest':
            order_papers = papers.order_by("-uploaded_date")
        elif ordering == "top_rated":
            order_papers = papers.order_by()
        elif ordering == "most_discussed":
            order_papers.sort(key=most_discussed_sort)

        page_num = request.GET["page"]
        data = order_papers
        url = request.build_absolute_uri()
        (count, nextPage, page) = BasicPaginator(data, page_num, url)
        serialized_data = PaperSerializer(page, many=True).data

        response = {
            'count': count,
            'has_next': page.has_next(),
            'next': nextPage,
            'results': serialized_data
        }

        return Response(response, status=200)


