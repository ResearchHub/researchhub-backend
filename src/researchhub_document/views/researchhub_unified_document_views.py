import datetime
from collections import OrderedDict

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


from hypothesis.models import Hypothesis
from paper.utils import get_cache_key
from researchhub_document.models import (
    ResearchhubUnifiedDocument,
    ResearchhubPost
)
from researchhub_document.utils import reset_unified_document_cache
from paper.utils import (
    invalidate_top_rated_cache,
    invalidate_newest_cache,
    invalidate_most_discussed_cache,
)
from researchhub_document.serializers import (
    ResearchhubUnifiedDocumentSerializer,
    DynamicUnifiedDocumentSerializer
)
from researchhub_document.related_models.constants.document_type import (
    PAPER,
    DISCUSSION,
    ELN,
    POSTS,
    HYPOTHESIS
)
from paper.models import Vote as PaperVote, Paper
from paper.serializers import PaperVoteSerializer
from discussion.reaction_serializers import (
    VoteSerializer as ReactionVoteSerializer
)
from discussion.models import Vote as ReactionVote
from researchhub_document.views.custom.unified_document_pagination import (
    UNIFIED_DOC_PAGE_SIZE,
    UnifiedDocPagination
)
from user.utils import reset_latest_acitvity_cache
from researchhub_document.permissions import (
    HasDocumentCensorPermission
)


class ResearchhubUnifiedDocumentViewSet(ModelViewSet):
    # TODO: calvinhlee - look into permissions
    permission_classes = [
        IsAuthenticated,
    ]
    dynamic_serializer_class = DynamicUnifiedDocumentSerializer
    pagination_class = UnifiedDocPagination
    queryset = ResearchhubUnifiedDocument.objects.all()
    serializer_class = ResearchhubUnifiedDocumentSerializer

    @action(
        detail=True,
        methods=['put', 'patch', 'delete'],
        permission_classes=[
            HasDocumentCensorPermission
        ]
    )
    def censor(self, request, pk=None):
        doc = self.get_object()
        doc.is_removed = True
        doc.save()

        return Response(
            self.get_serializer(instance=doc).data,
            status=200
        )

    @action(
        detail=True,
        methods=['put', 'patch'],
        permission_classes=[
            HasDocumentCensorPermission
        ]
    )
    def restore(self, request, pk=None):
        doc = self.get_object()
        doc.is_removed = False
        doc.save()

        return Response(
            self.get_serializer(instance=doc).data,
            status=200
        )

    def update(self, request, *args, **kwargs):
        update_response = super().update(request, *args, **kwargs)

        hub_ids = list(self.get_object().hubs.values_list('pk', flat=True))
        hub_ids.append(0)

        reset_unified_document_cache(hub_ids)
        reset_latest_acitvity_cache(
            ','.join([str(hub_id) for hub_id in hub_ids])
        )
        invalidate_top_rated_cache(hub_ids)
        invalidate_newest_cache(hub_ids)
        invalidate_most_discussed_cache(hub_ids)

        return update_response

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

    def _get_serializer_context(self):
        context = {
            'doc_duds_get_documents': {
                '_include_fields': [
                    'abstract',
                    'aggregate_citation_consensus',
                    'created_by',
                    'created_date',
                    'first_preview',
                    'hot_score',
                    'hubs',
                    'id',
                    'discussion_count',
                    'paper_title',
                    'renderable_text',
                    'score',
                    'slug',
                    'title',
                    'uploaded_by',
                    'uploaded_date',
                ]
            },
            'doc_dps_get_hubs': {
                '_include_fields': [
                    'id',
                    'name',
                    'is_locked',
                    'slug',
                    'is_removed',
                    'hub_image'
                ]
            },
            'pap_dps_get_hubs': {
                '_include_fields': [
                    'id',
                    'name',
                    'is_locked',
                    'slug',
                    'is_removed',
                    'hub_image',
                ]
            },
            'doc_dps_get_created_by': {
                '_include_fields': [
                    'author_profile',
                ]
            },
            'pap_dps_get_uploaded_by': {
                '_include_fields': [
                    'author_profile',
                ]
            },
            'usr_dus_get_author_profile': {
                '_include_fields': [
                    'id',
                    'first_name',
                    'last_name',
                    'profile_image',
                ]
            },
            'doc_duds_get_created_by': {
                '_include_fields': [
                    'author_profile',
                ]
            },
            'hyp_dhs_get_created_by': {
                '_include_fields': [
                    'author_profile',
                ]
            },
            'hyp_dhs_get_hubs': {
                '_include_fields': [
                    'id',
                    'name',
                    'is_locked',
                    'slug',
                    'is_removed',
                    'hub_image',
                ]
            }
        }
        return context

    def get_filtered_queryset(
        self,
        document_type,
        filtering,
        hub_id,
        start_date,
        end_date
    ):
        papers = Paper.objects.filter(
            uploaded_by__isnull=False
        ).values_list(
            'unified_document'
        )
        posts = ResearchhubPost.objects.filter(
            created_by__isnull=False
        ).values_list(
            'unified_document'
        )
        hypothesis = Hypothesis.objects.filter(
            created_by__isnull=False
        ).values_list(
            'unified_document'
        )
        filtered_ids = papers.union(posts, hypothesis)
        qs = self.queryset.filter(
            id__in=filtered_ids,
            is_removed=False
        )

        if document_type == PAPER.lower():
            qs = qs.filter(
                document_type=PAPER
            )
        elif document_type == POSTS.lower():
            qs = qs.filter(
                document_type__in=[DISCUSSION, ELN]
            )
        elif document_type == HYPOTHESIS.lower():
            qs = qs.filter(
                document_type=HYPOTHESIS
            )
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
            paper_votes = PaperVote.objects.filter(
                created_date__range=(start_date, end_date)
            ).values_list('paper__unified_document', flat=True)
            post_votes = ResearchhubPost.objects.filter(
                votes__created_date__range=(start_date, end_date)
            ).values_list('unified_document', flat=True)
            hypo_votes = Hypothesis.objects.filter(
                votes__created_date__range=(start_date, end_date)
            ).values_list('unified_document', flat=True)
            unified_document_ids = paper_votes.union(post_votes, hypo_votes)

            qs = qs.filter(
                id__in=unified_document_ids
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
        subscribed_hubs = query_params.get('subscribed_hubs', 'false')

        if subscribed_hubs == 'true' and not is_anonymous:
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
                [filtering],
                time_difference.days
            )

        documents = self.get_filtered_queryset(
            document_request_type,
            filtering,
            hub_id,
            start_date,
            end_date
        )

        context = self._get_serializer_context()
        page = self.paginate_queryset(documents)

        serializer = self.dynamic_serializer_class(
            page,
            _include_fields=[
                'documents',
                'document_type',
                'hot_score',
                'score',
            ],
            many=True,
            context=context
        )
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
            all_documents = {}
            for hub in hubs.iterator():
                hub_name = hub.slug
                cache_pk = f'{document_request_type}_{hub_name}'
                cache_key = get_cache_key('documents', cache_pk)
                cache_hit = cache.get(cache_key)
                if cache_hit:
                    for hit in cache_hit:
                        documents = hit['documents']
                        documents_type = type(documents)
                        if document_request_type == 'all':
                            if documents_type not in (OrderedDict, dict):
                                # This is hit when the document is a
                                # researchhub post.
                                if len(documents) == 0:
                                    continue
                                else:
                                    document = documents[0]
                            else:
                                # This is hit when the document is a paper
                                document = documents
                        elif document_request_type == 'posts':
                            if documents_type not in (OrderedDict, dict):
                                if len(documents) == 0:
                                    continue
                                else:
                                    document = documents[0]
                            else:
                                continue
                        else:
                            if documents_type in (OrderedDict, dict):
                                document = documents
                            else:
                                continue

                        document_id = document['id']
                        if document_id not in all_documents:
                            all_documents[document_id] = hit
            all_documents = list(all_documents.values())

            if len(all_documents) < 1:
                all_documents = self.get_filtered_queryset(
                    document_request_type,
                    filtering,
                    default_hub_id,
                    start_date,
                    end_date
                )
                all_documents = all_documents.filter(
                    hubs__in=hubs.all()
                ).distinct()
            else:
                all_documents = sorted(
                    all_documents, key=lambda doc: -doc['hot_score']
                )
                all_documents = all_documents[:UNIFIED_DOC_PAGE_SIZE]
                next_page = request.build_absolute_uri()
                if len(all_documents) < UNIFIED_DOC_PAGE_SIZE:
                    next_page = None
                else:
                    next_page = replace_query_param(next_page, 'page', 2)
                res = {
                    'count': len(all_documents),
                    'next': next_page,
                    'results': all_documents
                }
                return Response(res, status=status.HTTP_200_OK)
        else:
            all_documents = self.get_filtered_queryset(
                document_request_type,
                filtering,
                default_hub_id,
                start_date,
                end_date
            )
            all_documents = all_documents.filter(
                hubs__in=hubs.all()
            ).distinct()

        # if all_documents.count() < 1 and hubs.exists():
        #     if document_request_type == 'all':
        #         trending_pk = 'all_0_-hot_score_today'
        #     elif document_request_type == 'posts':
        #         trending_pk = 'posts_0_-hot_score_today'
        #     else:
        #         trending_pk = 'paper_0_-hot_score_today'

        #     cache_key_hub = get_cache_key('hub', trending_pk)
        #     cache_hit = cache.get(cache_key_hub)

        #     if cache_hit and page_number == 1:
        #         return Response(cache_hit)

        #     all_documents = self.get_filtered_queryset(
        #         document_request_type,
        #         filtering,
        #         default_hub_id,
        #         start_date,
        #         end_date
        #     )
        #     all_documents = all_documents.filter(
        #         hubs__in=hubs.all()
        #     ).distinct()

        context = self._get_serializer_context()
        page = self.paginate_queryset(all_documents)
        serializer = self.dynamic_serializer_class(
            page,
            _include_fields=[
                'documents',
                'document_type',
                'hot_score',
                'score'
            ],
            many=True,
            context=context
        )
        serializer_data = serializer.data
        return self.get_paginated_response(serializer_data)

    @action(
        detail=False,
        methods=['get'],
        permission_classes=[AllowAny]
    )
    def check_user_vote(self, request):
        paper_ids = request.query_params.get('paper_ids', '')
        post_ids = request.query_params.get('post_ids', '')
        hypothesis_ids = request.query_params.get('hypothesis_ids', '')

        if paper_ids:
            paper_ids = paper_ids.split(',')
        if post_ids:
            post_ids = post_ids.split(',')
        if hypothesis_ids:
            hypothesis_ids = hypothesis_ids.split(',')

        user = request.user
        response = {
            'hypothesis': {},
            'papers': {},
            'posts': {},
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
                post_votes = get_user_votes(
                    user,
                    post_ids,
                    ContentType.objects.get_for_model(ResearchhubPost)
                )
                for vote in post_votes.iterator():
                    response['posts'][vote.object_id] = (
                        ReactionVoteSerializer(instance=vote).data
                    )
            if hypothesis_ids:
                hypo_votes = get_user_votes(
                    user,
                    hypothesis_ids,
                    ContentType.objects.get_for_model(Hypothesis)
                )
                for vote in hypo_votes.iterator():
                    response['hypothesis'][vote.object_id] = (
                        ReactionVoteSerializer(instance=vote).data
                    )
        return Response(response, status=status.HTTP_200_OK)


def get_user_votes(created_by, doc_ids, reaction_content_type):
    return ReactionVote.objects.filter(
        content_type=reaction_content_type,
        object_id__in=doc_ids,
        created_by=created_by
    )
