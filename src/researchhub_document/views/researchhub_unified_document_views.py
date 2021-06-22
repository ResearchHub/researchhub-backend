import datetime

from django.core.cache import cache
from django.db.models import (
    Q,
    Count
)
from django.contrib.contenttypes.models import ContentType
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.viewsets import ModelViewSet
from rest_framework.response import Response
from rest_framework.utils.urls import replace_query_param
from rest_framework.permissions import (
    AllowAny,
    IsAuthenticated
)


from paper.utils import get_cache_key
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.utils import reset_unified_document_cache
from researchhub_document.serializers import (
  ResearchhubUnifiedDocumentSerializer
)
from researchhub_document.related_models.constants.document_type import (
    PAPER,
    DISCUSSION,
    ELN,
    POSTS
)

from paper.models import Vote as PaperVote
from paper.serializers import PaperVoteSerializer
from discussion.reaction_serializers import (
    VoteSerializer as DiscussionVoteSerializer
)
from discussion.models import Vote as DiscussionVote


class ResearchhubUnifiedDocumentViewSet(ModelViewSet):
    # TODO: calvinhlee - look into permissions
    permission_classes = [
        IsAuthenticated,
    ]
    queryset = ResearchhubUnifiedDocument.objects
    serializer_class = ResearchhubUnifiedDocumentSerializer

    def _get_document_filtering(self, query_params):
        filtering = query_params.get('ordering', None)
        if filtering == 'removed':
            filtering = 'removed'
        elif filtering == 'top_rated':
            filtering = '-score'
        elif filtering == 'most_discussed':
            filtering = '-discussed'
        elif filtering == 'newest':
            filtering = '-created_date'
        elif filtering == 'hot':
            filtering = '-hot_score'
        elif filtering == 'user_uploaded':
            filtering = 'user_uploaded'
        else:
            filtering = '-score'
        return filtering

    def get_filtered_queryset(
        self,
        document_type,
        filtering,
        hub_id,
        start_date,
        end_date
    ):
        qs = self.queryset.filter(is_removed=False)

        if document_type == PAPER.lower():
            qs = qs.filter(
                document_type=PAPER
            )
        elif document_type == POSTS.lower():
            qs = qs.filter(document_type__in=[DISCUSSION, ELN])
        else:
            qs = qs.all()

        hub_id = int(hub_id)
        if hub_id != 0:
            qs = qs.filter(hubs__in=[hub_id])

        if filtering == 'removed':
            qs = qs.filter(
                is_removed=True
            ).order_by(
                '-created_date'
            )
        elif filtering == '-score':
            qs = qs.filter(
                created_date__range=[start_date, end_date],
            ).order_by(
                filtering
            )
        elif filtering == '-discussed':
            paper_threads_count = Count('paper__threads')
            paper_comments_count = Count('paper__threads__comments')
            posts_threads__count = Count('posts__threads')
            posts_comments_count = Count('posts__threads__comments')

            qs = qs.filter(
                (
                    Q(paper__threads__isnull=False) |
                    Q(posts__threads__isnull=False)
                )
            )
            qs = qs.filter(
                (
                    Q(paper__threads__created_date__range=[
                        start_date, end_date
                    ]) |
                    Q(paper__threads__comments__created_date__range=[
                        start_date, end_date
                    ]) |
                    Q(posts__threads__created_date__range=[
                        start_date, end_date
                    ]) |
                    Q(posts__threads__comments__created_date__range=[
                        start_date, end_date
                    ])
                ),
            ).annotate(
                discussed=(
                    paper_threads_count +
                    paper_comments_count +
                    posts_threads__count +
                    posts_comments_count
                )
            ).order_by(
                '-discussed'
            )
        elif filtering == '-created_date':
            qs = qs.order_by(filtering)
        elif filtering == '-hot_score':
            qs = qs.order_by(filtering)
        elif filtering == 'user_uploaded':
            qs = qs.filter(
                (
                    Q(paper__uploaded_by__isnull=False) |
                    Q(posts__created_by__isnull=False)
                )
            ).order_by(
                '-created_date'
            )
        else:
            qs = qs.order_by('-hot_score')

        return qs

    def _get_unifed_document_cache_hit(
        self,
        document_type,
        filtering,
        hub_id,
        page_number,
        time_difference
    ):
        cache_hit = None
        if page_number == 1 and 'removed' not in filtering:
            cache_pk = ''
            if time_difference.days > 365:
                cache_pk = f'{document_type}_{hub_id}_{filtering}_all_time'
            elif time_difference.days == 365:
                cache_pk = f'{document_type}_{hub_id}_{filtering}_year'
            elif time_difference.days == 30 or time_difference.days == 31:
                cache_pk = f'{document_type}_{hub_id}_{filtering}_month'
            elif time_difference.days == 7:
                cache_pk = f'{document_type}_{hub_id}_{filtering}_week'
            else:
                cache_pk = f'{document_type}_{hub_id}_{filtering}_today'

            cache_key_hub = get_cache_key('hub', cache_pk)
            cache_hit = cache.get(cache_key_hub)

        if cache_hit:
            return cache_hit
        return None

    @action(
        detail=False,
        methods=['get'],
        permission_classes=[AllowAny]
    )
    def get_unified_documents(self, request):
        is_anonymous = request.user.is_anonymous
        query_params = request.query_params
        subscribed_hubs = query_params.get('subscribed_hubs', False)

        if subscribed_hubs and not is_anonymous:
            return self._get_subscribed_unified_documents(request)

        document_request_type = query_params.get('type', 'all')
        hub_id = query_params.get('hub_id', 0)
        page_number = int(query_params.get('page', 1))
        start_date = datetime.datetime.fromtimestamp(
            int(request.GET.get('start_date__gte', 0)),
            datetime.timezone.utc
        )
        end_date = datetime.datetime.fromtimestamp(
            int(request.GET.get('end_date__lte', 0)),
            datetime.timezone.utc
        )
        time_difference = end_date - start_date
        filtering = self._get_document_filtering(query_params)
        cache_hit = self._get_unifed_document_cache_hit(
            document_request_type,
            filtering,
            hub_id,
            page_number,
            time_difference
        )

        if cache_hit and page_number == 1:
            return Response(cache_hit)
        elif not cache_hit and page_number == 1:
            reset_unified_document_cache(
                [hub_id],
                [document_request_type],
                filtering,
                time_difference.days
            )

        documents = self.get_filtered_queryset(
            document_request_type,
            filtering,
            hub_id,
            start_date,
            end_date
        )

        context = self.get_serializer_context()
        context['user_no_balance'] = True
        context['exclude_promoted_score'] = True
        context['include_wallet'] = False

        page = self.paginate_queryset(documents)
        serializer = self.serializer_class(page, many=True, context=context)
        serializer_data = serializer.data

        return self.get_paginated_response(serializer_data)

    def _get_subscribed_unified_documents(self, request):
        default_hub_id = 0
        hubs = request.user.subscribed_hubs
        query_params = request.query_params
        document_request_type = query_params.get('type', 'all')
        page_number = int(query_params.get('page', 1))
        start_date = datetime.datetime.fromtimestamp(
            int(request.GET.get('start_date__gte', 0)),
            datetime.timezone.utc
        )
        end_date = datetime.datetime.fromtimestamp(
            int(request.GET.get('end_date__lte', 0)),
            datetime.timezone.utc
        )
        filtering = self._get_document_filtering(query_params)

        if filtering == '-hot_score' and page_number == 1:
            documents = {}
            for hub in hubs.iterator():
                hub_name = hub.slug
                cache_pk = f'{document_request_type}_{hub_name}'
                cache_key = get_cache_key('documents', cache_pk)
                cache_hit = cache.get(cache_key)
                if cache_hit:
                    for hit in cache_hit:
                        document_id = hit['id']
                        abstract = hit.get('abstract', None)
                        if document_id not in documents and abstract:
                            documents[document_id] = hit
            documents = list(documents.values())

            if len(documents) < 1:
                documents = self.get_filtered_queryset(
                    document_request_type,
                    filtering,
                    default_hub_id,
                    start_date,
                    end_date
                )
                documents = documents.filter(
                    hubs__in=hubs.all()
                ).distinct()
            else:
                documents = sorted(
                    documents, key=lambda doc: -doc['hot_score']
                )
                documents = documents[:10]
                next_page = request.build_absolute_uri()
                if len(documents) < 10:
                    next_page = None
                else:
                    next_page = replace_query_param(next_page, 'page', 2)
                res = {
                    'count': len(documents),
                    'next': next_page,
                    'results': documents
                }
                return Response(res, status=status.HTTP_200_OK)
        else:
            documents = self.get_filtered_queryset(
                document_request_type,
                filtering,
                default_hub_id,
                start_date,
                end_date
            )
            documents = documents.filter(
                hubs__in=hubs.all()
            ).distinct()

        if documents.count() < 1:
            trending_pk = 'all_0_-hot_score_today'
            cache_key_hub = get_cache_key('hub', trending_pk)
            cache_hit = cache.get(cache_key_hub)

            if cache_hit and page_number == 1:
                return Response(cache_hit)

            documents = self.get_filtered_queryset(
                document_request_type,
                filtering,
                default_hub_id,
                start_date,
                end_date
            )

        context = self.get_serializer_context()
        context['user_no_balance'] = True
        context['exclude_promoted_score'] = True
        context['include_wallet'] = False

        page = self.paginate_queryset(documents)
        serializer = self.serializer_class(page, many=True, context=context)
        serializer_data = serializer.data
        return self.get_paginated_response(serializer_data)

    @action(
        detail=False,
        methods=['get'],
        permission_classes=[AllowAny]
    )
    def check_user_vote(self, request):
        post_content_type = ContentType.objects.get(model='researchhubpost')
        paper_ids = request.query_params.get('paper_ids', '')
        post_ids = request.query_params.get('post_ids', '')

        if paper_ids:
            paper_ids = paper_ids.split(',')

        if post_ids:
            post_ids = post_ids.split(',')

        user = request.user
        response = {
            'posts': {},
            'papers': {},
        }

        if user.is_authenticated:
            if paper_ids:
                paper_votes = PaperVote.objects.filter(
                    paper__id__in=paper_ids,
                    created_by=user
                )
                for vote in paper_votes.iterator():
                    paper_id = vote.paper_id
                    response['papers'][paper_id] = PaperVoteSerializer(
                        instance=vote
                    ).data
            if post_ids:
                post_votes = DiscussionVote.objects.filter(
                    content_type=post_content_type,
                    object_id__in=post_ids,
                    created_by=user
                )
                for vote in post_votes.iterator():
                    post_id = vote.object_id
                    response['posts'][post_id] = DiscussionVoteSerializer(
                        instance=vote
                    ).data

        return Response(response, status=status.HTTP_200_OK)
