import json
import datetime
import base64

from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import IntegrityError
from django.db.models import (
    Count,
    Q,
    Prefetch,
    F,
    Sum,
    Value,
    IntegerField
)
from django.db.models.functions import (
    Coalesce,
    Cast
)
from django_filters.rest_framework import DjangoFilterBackend
from django.contrib.postgres.search import TrigramSimilarity
from elasticsearch.exceptions import ConnectionError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.utils.urls import replace_query_param
from rest_framework.permissions import (
    IsAuthenticatedOrReadOnly,
    IsAuthenticated
)
from rest_framework.response import Response

from bullet_point.models import BulletPoint
from google_analytics.signals import get_event_hit_response
from paper.exceptions import PaperSerializerError
from paper.filters import PaperFilter
from paper.models import (
    AdditionalFile,
    Figure,
    Flag,
    Paper,
    Vote,
    FeaturedPaper
)
from paper.tasks import censored_paper_cleanup
from paper.permissions import (
    CreatePaper,
    UpdateOrDeleteAdditionalFile,
    FlagPaper,
    IsAuthor,
    IsModeratorOrVerifiedAuthor,
    UpdatePaper,
    UpvotePaper,
    DownvotePaper
)
from paper.serializers import (
    AdditionalFileSerializer,
    BookmarkSerializer,
    HubPaperSerializer,
    FlagSerializer,
    FigureSerializer,
    PaperSerializer,
    PaperReferenceSerializer,
    PaperVoteSerializer,
    FeaturedPaperSerializer,
)
from paper.utils import (
    clean_abstract,
    get_csl_item,
    get_pdf_location_for_csl_item,
    get_cache_key,
    invalidate_top_rated_cache,
    invalidate_newest_cache,
    invalidate_most_discussed_cache,
    reset_cache,
    add_default_hub
)
from purchase.models import Purchase
from researchhub.lib import get_paper_id_from_path
from reputation.models import Contribution
from reputation.tasks import create_contribution
from user.models import Author
from utils.http import GET, POST, check_url_contains_pdf
from utils.sentry import log_error, log_info
from utils.permissions import CreateOrUpdateIfAllowed
from utils.throttles import THROTTLE_CLASSES
from utils.siftscience import events_api, decisions_api
from rest_framework.permissions import AllowAny


class PaperViewSet(viewsets.ModelViewSet):
    queryset = Paper.objects.filter()
    serializer_class = PaperSerializer
    filter_backends = (SearchFilter, DjangoFilterBackend, OrderingFilter)
    search_fields = ('title', 'doi', 'paper_title')
    filter_class = PaperFilter
    throttle_classes = THROTTLE_CLASSES
    ordering = ('-uploaded_date')

    permission_classes = [
        IsAuthenticatedOrReadOnly
        & CreatePaper
        & UpdatePaper
        & CreateOrUpdateIfAllowed
    ]

    def prefetch_lookups(self):
        return (
            'uploaded_by',
            'uploaded_by__bookmarks',
            'uploaded_by__author_profile',
            'uploaded_by__author_profile__user',
            'uploaded_by__subscribed_hubs',
            'authors',
            'authors__user',
            Prefetch(
                'bullet_points',
                queryset=BulletPoint.objects.filter(
                    is_head=True,
                    is_removed=False,
                    ordinal__isnull=False
                ).order_by('ordinal')
            ),
            'summary',
            'summary__previous',
            'summary__proposed_by__bookmarks',
            'summary__proposed_by__subscribed_hubs',
            'summary__proposed_by__author_profile',
            'summary__paper',
            'moderators',
            'hubs',
            'hubs__subscribers',
            'votes',
            'flags',
            'purchases',
            'threads',
            'threads__comments',
            Prefetch(
                'figures',
                queryset=Figure.objects.filter(
                    figure_type=Figure.FIGURE
                ).order_by(
                    'created_date'
                ),
                to_attr='figure_list',
            ),
            Prefetch(
                'figures',
                queryset=Figure.objects.filter(
                    figure_type=Figure.PREVIEW
                ).order_by(
                    'created_date'
                ),
                to_attr='preview_list',
            ),
            Prefetch(
                'votes',
                queryset=Vote.objects.filter(
                    created_by=self.request.user.id,
                ),
                to_attr='vote_created_by',
            ),
            Prefetch(
                'flags',
                queryset=Flag.objects.filter(
                    created_by=self.request.user.id,
                ),
                to_attr='flag_created_by',
            ),
        )

    def get_queryset(self, prefetch=True, include_autopull=False):
        query_params = self.request.query_params
        queryset = self.queryset
        ordering = query_params.get('ordering', None)
        external_source = query_params.get('external_source', False)

        if query_params.get('make_public') or query_params.get('all') or (ordering and 'removed' in ordering):
            pass
        else:
            queryset = self.queryset.filter(is_removed=False)

        # if ordering == 'newest' and not include_autopull:
        #     queryset = queryset.filter(uploaded_by__isnull=False)

        user = self.request.user
        if user.is_staff:
            return queryset

        if not user.is_anonymous and user.moderator and external_source:
            queryset = queryset.filter(
                is_removed=False,
                retrieved_from_external_source=True
            )
        if prefetch:
            return queryset.prefetch_related(
                *self.prefetch_lookups()
            )
        else:
            return queryset

    def create(self, *args, **kwargs):
        try:
            response = super().create(*args, **kwargs)
            request = args[0]
            hub_ids = list(request.POST['hubs'])
            reset_cache(hub_ids)
            return response
        except IntegrityError as e:
            return self._get_integrity_error_response(e)
        except PaperSerializerError as e:
            return Response(str(e), status=status.HTTP_400_BAD_REQUEST)

    def _get_integrity_error_response(self, error):
        error_message = str(error)
        parts = error_message.split('DETAIL:')
        try:
            error_message = parts[1].strip()
            if 'url' in error_message:
                error_message = 'A paper with this url already exists.'
            if 'doi' in error_message:
                error_message = 'A paper with this DOI already exists.'
        except IndexError:
            error_message = 'A paper with this url or DOI already exists.'
        return Response(
            {'error': error_message},
            status=status.HTTP_400_BAD_REQUEST
        )

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        cache_key = get_cache_key('paper', instance.id)
        cache_hit = cache.get(cache_key)
        if cache_hit is not None:
            vote = self.serializer_class(
                context={'request': request}
            ).get_user_vote(instance)
            cache_hit['user_vote'] = vote
            return Response(cache_hit)

        if request.query_params.get('make_public') and not instance.is_public:
            instance.is_public = True
            instance.save()
        serializer = self.get_serializer(instance)
        serializer_data = serializer.data

        cache.set(cache_key, serializer_data, timeout=60*60*24*7)
        return Response(serializer_data)

    def list(self, request, *args, **kwargs):
        default_pagination_class = self.pagination_class
        if request.query_params.get('limit'):
            self.pagination_class = LimitOffsetPagination
        else:
            self.pagination_class = default_pagination_class
        return super().list(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()

        # TODO: This needs improvement so we guarantee that we are tracking
        # file created location when a file is actually being added and not
        # just any updates to the paper
        created_location = None
        if request.query_params.get('created_location') == 'progress':
            created_location = Paper.CREATED_LOCATION_PROGRESS
            request.data['file_created_location'] = created_location

        response = super().update(request, *args, **kwargs)

        if (created_location is not None) and not request.user.is_anonymous:
            instance = self.get_object()
            self._send_created_location_ga_event(instance, request.user)

        hub_ids = request.data.get('hubs', [0])
        if type(hub_ids) is not list:
            hub_ids = list(hub_ids)

        reset_cache(hub_ids)
        invalidate_top_rated_cache(hub_ids)
        invalidate_newest_cache(hub_ids)
        invalidate_most_discussed_cache(hub_ids)
        instance.reset_cache()
        return response

    def _send_created_location_ga_event(self, instance, user):
        created = True

        category = 'Paper'

        label = 'Pdf from Progress'

        action = 'Upload'

        user_id = user.id

        paper_id = instance.id

        date = instance.updated_date

        return get_event_hit_response(
            instance,
            created,
            category,
            label,
            action=action,
            user_id=user_id,
            paper_id=paper_id,
            date=date
        )

    @action(
        detail=True,
        methods=['put', 'patch', 'delete'],
        permission_classes=[IsAuthenticated, IsModeratorOrVerifiedAuthor]
    )
    def censor(self, request, pk=None):
        paper = self.get_object()
        paper_id = paper.id
        cache_key = get_cache_key('paper', paper_id)
        cache.delete(cache_key)
        hub_ids = list(paper.hubs.values_list('id', flat=True))
        hub_ids = add_default_hub(hub_ids)

        content_id = f'{type(paper).__name__}_{paper_id}'
        user = request.user
        content_creator = paper.uploaded_by
        if content_creator:
            events_api.track_flag_content(
                content_creator,
                content_id,
                user.id
            )
            decisions_api.apply_bad_content_decision(
                content_creator,
                content_id,
                'MANUAL_REVIEW',
                user
            )
            decisions_api.apply_bad_user_decision(
                content_creator,
                'MANUAL_REVIEW',
                user
            )

        Contribution.objects.filter(paper=paper).delete()
        paper.is_removed = True
        paper.save()
        censored_paper_cleanup.apply_async((paper_id,), priority=3)

        reset_cache(hub_ids)
        invalidate_top_rated_cache(hub_ids)
        invalidate_newest_cache(hub_ids)
        invalidate_most_discussed_cache(hub_ids)
        return Response('Paper was deleted.', status=200)

    @action(
        detail=True,
        methods=['put', 'patch', 'delete'],
        permission_classes=[IsAuthenticated, IsModeratorOrVerifiedAuthor]
    )
    def censor_pdf(self, request, pk=None):
        paper = self.get_object()
        paper_id = paper.id
        paper.file = None
        paper.url = None
        paper.pdf_url = None
        paper.figures.all().delete()
        paper.save()

        content_id = f'{type(paper).__name__}_{paper_id}'
        user = request.user
        content_creator = paper.uploaded_by
        events_api.track_flag_content(
            content_creator,
            content_id,
            user.id
        )
        decisions_api.apply_bad_content_decision(
            content_creator,
            content_id,
            'MANUAL_REVIEW',
            user
        )
        decisions_api.apply_bad_user_decision(
            content_creator,
            'MANUAL_REVIEW',
            user
        )

        hub_ids = list(paper.hubs.values_list('id', flat=True))
        hub_ids = add_default_hub(hub_ids)

        reset_cache(hub_ids)
        invalidate_top_rated_cache(hub_ids)
        invalidate_newest_cache(hub_ids)
        invalidate_most_discussed_cache(hub_ids)
        paper.reset_cache()
        return Response(
            self.get_serializer(instance=paper).data,
            status=200
        )

    @action(
        detail=True,
        methods=['post', 'put', 'patch'],
        permission_classes=[IsAuthor]
    )
    def assign_moderator(self, request, pk=None):
        '''Assign users as paper moderators'''
        paper = self.get_object()
        moderators = request.data.get('moderators')
        if not isinstance(moderators, list):
            moderators = [moderators]
        paper.moderators.add(*moderators)
        paper.save()
        return Response(PaperSerializer(paper).data)

    @action(
        detail=True,
        methods=['post'],
        permission_classes=[
            IsAuthenticatedOrReadOnly
            & CreateOrUpdateIfAllowed
        ]
    )
    def bookmark(self, request, pk=None):
        paper = self.get_object()
        user = request.user

        if paper in user.bookmarks.all():
            return Response('Bookmark already added', status=400)
        else:
            user.bookmarks.add(paper)
            user.save()
            serialized = BookmarkSerializer({
                'user': user.id,
                'bookmarks': user.bookmarks.all()
            })
            return Response(serialized.data, status=201)

    @bookmark.mapping.delete
    def delete_bookmark(self, request, pk=None):
        paper = self.get_object()
        user = request.user

        try:
            user.bookmarks.remove(paper)
            user.save()
            return Response(paper.id, status=200)
        except Exception as e:
            print(e)
            return Response(
                f'Failed to remove {paper.id} from bookmarks',
                status=400
            )

    @action(
        detail=True,
        methods=['post'],
        permission_classes=[
            FlagPaper
            & CreateOrUpdateIfAllowed
        ]  # Also applies to delete_flag below
    )
    def flag(self, request, pk=None):
        paper = self.get_object()
        reason = request.data.get('reason')
        referrer = request.user
        flag = Flag.objects.create(
            paper=paper,
            created_by=referrer,
            reason=reason
        )

        content_id = f'{type(paper).__name__}_{paper.id}'
        events_api.track_flag_content(
            paper.uploaded_by,
            content_id,
            referrer.id
        )
        return Response(FlagSerializer(flag).data, status=201)

    @flag.mapping.delete
    def delete_flag(self, request, pk=None):
        try:
            flag = Flag.objects.get(
                paper=pk,
                created_by=request.user.id
            )
            flag_id = flag.id
            flag.delete()
            return Response(flag_id, status=200)
        except Exception as e:
            return Response(f'Failed to delete flag: {e}', status=400)

    @action(detail=True, methods=[GET])
    def referenced_by(self, request, pk=None):
        paper = self.get_object()
        queryset = paper.referenced_by.all()
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = PaperReferenceSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=[GET])
    def references(self, request, pk=None):
        paper = self.get_object()
        queryset = paper.references.all()
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = PaperReferenceSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'])
    def user_vote(self, request, pk=None):
        paper = self.get_object()
        user = request.user
        vote = retrieve_vote(user, paper)
        return get_vote_response(vote, 200)

    @user_vote.mapping.delete
    def delete_user_vote(self, request, pk=None):
        try:
            paper = self.get_object()
            user = request.user
            vote = retrieve_vote(user, paper)
            vote_id = vote.id
            vote.delete()
            return Response(vote_id, status=200)
        except Exception as e:
            return Response(f'Failed to delete vote: {e}', status=400)

    @action(
        detail=True,
        methods=['post', 'put', 'patch'],
        permission_classes=[
            UpvotePaper
            & CreateOrUpdateIfAllowed
        ]
    )
    def upvote(self, request, pk=None):
        paper = self.get_object()
        hub_ids = list(paper.hubs.values_list('id', flat=True))
        hub_ids = add_default_hub(hub_ids)
        user = request.user

        vote_exists = find_vote(user, paper, Vote.UPVOTE)

        if vote_exists:
            return Response(
                'This vote already exists',
                status=status.HTTP_400_BAD_REQUEST
            )
        response = update_or_create_vote(request, user, paper, Vote.UPVOTE)

        reset_cache(hub_ids)
        invalidate_top_rated_cache(hub_ids)
        invalidate_newest_cache(hub_ids)
        invalidate_most_discussed_cache(hub_ids)
        paper.reset_cache()

        return response

    @action(
        detail=True,
        methods=['post', 'put', 'patch'],
        permission_classes=[
            DownvotePaper
            & CreateOrUpdateIfAllowed
        ]
    )
    def downvote(self, request, pk=None):
        paper = self.get_object()
        hub_ids = list(paper.hubs.values_list('id', flat=True))
        hub_ids = add_default_hub(hub_ids)
        user = request.user

        vote_exists = find_vote(user, paper, Vote.DOWNVOTE)

        if vote_exists:
            return Response(
                'This vote already exists',
                status=status.HTTP_400_BAD_REQUEST
            )
        response = update_or_create_vote(request, user, paper, Vote.DOWNVOTE)

        reset_cache(hub_ids)
        invalidate_top_rated_cache(hub_ids)
        invalidate_newest_cache(hub_ids)
        invalidate_most_discussed_cache(hub_ids)
        paper.reset_cache()

        return response

    @action(
        detail=False,
        methods=['get'],
    )
    def check_user_vote(self, request):
        paper_ids = request.query_params['paper_ids'].split(',')
        user = request.user
        response = {}

        if user.is_authenticated:
            votes = Vote.objects.filter(paper__id__in=paper_ids, created_by=user)

            for vote in votes.iterator():
                paper_id = vote.paper_id
                data = PaperVoteSerializer(instance=vote).data
                response[paper_id] = data

        return Response(response, status=status.HTTP_200_OK)

    @action(detail=False, methods=[POST])
    def check_url(self, request):
        url = request.data.get('url', None)
        url_is_pdf = check_url_contains_pdf(url)
        data = {'found_file': url_is_pdf}
        return Response(data, status=status.HTTP_200_OK)

    @staticmethod
    def search_by_csl_item(csl_item):
        """
        Perform an elasticsearch query for papers matching
        the input CSL_Item.
        """
        from elasticsearch_dsl import Search, Q
        search = Search(index="paper")
        title = csl_item.get('title', '')
        query = Q("match", title=title) | Q("match", paper_title=title)
        if csl_item.get('DOI'):
            query |= Q("match", doi=csl_item['DOI'])
        search.query(query)
        return search

    @action(detail=False, methods=['post'])
    def search_by_url(self, request):
        # TODO: Ensure we are saving data from here, license, title,
        # publish date, authors, pdf
        # handle pdf url, journal url, or pdf upload
        # TODO: Refactor
        """
        Retrieve bibliographic metadata and potential paper matches
        from the database for `url` (specified via request post data).
        """
        url = request.data.get('url').strip()
        data = {'url': url}

        if not url:
            return Response(
                "search_by_url requests must specify 'url'",
                status=status.HTTP_400_BAD_REQUEST
            )
        try:
            URLValidator()(url)
        except (ValidationError, Exception) as e:
            print(e)
            return Response(
                f"Double check that URL is valid: {url}",
                status=status.HTTP_400_BAD_REQUEST
            )

        url_is_pdf = check_url_contains_pdf(url)
        data['url_is_pdf'] = url_is_pdf

        duplicate_papers = Paper.objects.filter(
            Q(url__icontains=url) | Q(pdf_url__icontains=url)
        )
        if duplicate_papers.exists():
            duplicate_paper = duplicate_papers.first()
            serializer_data = self.serializer_class(
                duplicate_paper,
                context={'purchase_minimal_serialization': True}
            ).data
            data = {
                'key': 'url',
                'results': serializer_data
            }
            return Response(data, status=status.HTTP_403_FORBIDDEN)

        try:
            csl_item = get_csl_item(url)
        except Exception as error:
            data['warning'] = f"Generating csl_item failed with:\n{error}"
            log_error(error)
            csl_item = None

        if csl_item:
            # Cleaning csl data
            try:
                cleaned_title = csl_item.get('title', '').strip()
                duplicate_papers = Paper.objects.filter(
                    paper_title__icontains=cleaned_title
                ).annotate(
                    similarity=TrigramSimilarity('paper_title', cleaned_title)
                ).filter(
                    similarity__gt=0.7
                ).order_by(
                    'similarity'
                )[:3]

                if duplicate_papers.exists():
                    serializer_data = self.serializer_class(
                        duplicate_papers,
                        context={'purchase_minimal_serialization': True},
                        many=True
                    ).data
                    data = {
                        'key': 'title',
                        'results': serializer_data
                    }
                    return Response(data, status=status.HTTP_403_FORBIDDEN)
            except Exception as e:
                print(e)

            csl_item['title'] = cleaned_title
            abstract = csl_item.get('abstract', '')
            cleaned_abstract = clean_abstract(abstract)
            csl_item['abstract'] = cleaned_abstract

            url_is_unsupported_pdf = url_is_pdf and csl_item.get('URL') == url
            data['url_is_unsupported_pdf'] = url_is_unsupported_pdf
            csl_item.url_is_unsupported_pdf = url_is_unsupported_pdf
            data['csl_item'] = csl_item
            data['oa_pdf_location'] = get_pdf_location_for_csl_item(csl_item)
            doi = csl_item.get('DOI', None)

            duplicate_papers = Paper.objects.exclude(doi=None).filter(doi=doi)
            if duplicate_papers.exists():
                duplicate_paper = duplicate_papers.first()
                serializer_data = self.serializer_class(
                    duplicate_paper,
                    context={'purchase_minimal_serialization': True}
                ).data
                data = {
                    'key': 'doi',
                    'results': serializer_data
                }
                return Response(data, status=status.HTTP_403_FORBIDDEN)

            data['paper_publish_date'] = csl_item.get_date('issued', fill=True)

        if csl_item and request.data.get('search', False):
            # search existing papers
            search = self.search_by_csl_item(csl_item)
            try:
                search = search.execute()
            except ConnectionError:
                return Response(
                    "Search failed due to an elasticsearch ConnectionError.",
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            data['search'] = [hit.to_dict() for hit in search.hits]

        return Response(data, status=status.HTTP_200_OK)

    def calculate_paper_ordering(self, papers, ordering, start_date, end_date):
        if 'hot_score' in ordering:
            order_papers = papers.order_by(ordering)
        elif 'score' in ordering:
            boost_amount = Coalesce(
                Sum(
                    Cast(
                        'purchases__amount',
                        output_field=IntegerField()
                    ),
                    filter=Q(
                        purchases__paid_status=Purchase.PAID,
                        purchases__user__moderator=True,
                        purchases__amount__gt=0,
                        purchases__boost_time__gt=0
                        )
                    ),
                Value(0)
            )
            order_papers = papers.filter(
                uploaded_date__range=[start_date, end_date],
            ).annotate(
                total_score=boost_amount + F('score')
            ).order_by('-total_score')
        elif 'discussed' in ordering:
            threads_count = Count('threads')
            comments_count = Count('threads__comments')

            order_papers = papers.filter(
                Q(threads__source='researchhub') |
                Q(threads__comments__source='researchhub'),
                Q(threads__created_date__range=[
                    start_date, end_date
                ]) |
                Q(threads__comments__created_date__range=[
                    start_date, end_date
                ])
            ).annotate(
                discussed=threads_count + comments_count,
                discussed_secondary=F('discussion_count')
            ).order_by(
                ordering, ordering + '_secondary'
            )
        elif 'removed' in ordering:
            order_papers = papers.order_by('-uploaded_date')
        elif 'twitter_score' in ordering:
            order_papers = papers.order_by('-twitter_score')
        else:
            order_papers = papers.order_by(ordering)

        return order_papers

    @action(detail=False, methods=['get'])
    def get_hub_papers(self, request):
        subscribed_hubs = request.GET.get('subscribed_hubs', False)
        external_source = request.GET.get('external_source', False)
        is_anonymous = request.user.is_anonymous
        if subscribed_hubs and not is_anonymous:
            return self.subscribed_hub_papers(request)

        page_number = int(request.GET['page'])
        start_date = datetime.datetime.fromtimestamp(
            int(request.GET.get('start_date__gte', 0)),
            datetime.timezone.utc
        )
        end_date = datetime.datetime.fromtimestamp(
            int(request.GET.get('end_date__lte', 0)),
            datetime.timezone.utc
        )
        ordering = self._set_hub_paper_ordering(request)
        hub_id = request.GET.get('hub_id', 0)

        cache_hit = None
        time_difference = end_date - start_date
        if page_number == 1 and 'removed' not in ordering and not external_source:
            cache_pk = ''
            if time_difference.days > 365:
                cache_pk = f'{hub_id}_{ordering}_all_time'
            elif time_difference.days == 365:
                cache_pk = f'{hub_id}_{ordering}_year'
            elif time_difference.days == 30 or time_difference.days == 31:
                cache_pk = f'{hub_id}_{ordering}_month'
            elif time_difference.days == 7:
                cache_pk = f'{hub_id}_{ordering}_week'
            else:
                cache_pk = f'{hub_id}_{ordering}_today'

            cache_key_hub = get_cache_key('hub', cache_pk)
            cache_hit = cache.get(cache_key_hub)

            if cache_hit and page_number == 1:
                return Response(cache_hit)

        context = self.get_serializer_context()
        context['user_no_balance'] = True
        context['exclude_promoted_score'] = True
        context['include_wallet'] = False

        if not cache_hit and page_number == 1:
            reset_cache([hub_id], ordering, time_difference.days)

        papers = self._get_filtered_papers(hub_id, ordering)
        order_papers = self.calculate_paper_ordering(
            papers,
            ordering,
            start_date,
            end_date
        )
        page = self.paginate_queryset(order_papers)
        serializer = HubPaperSerializer(page, many=True, context=context)
        serializer_data = serializer.data

        res = self.get_paginated_response(
            {
                'data': serializer_data,
                'no_results': False,
                'feed_type': 'all'
            }
        )
        return res

    @action(
        detail=True,
        methods=['get'],
        permission_classes=[IsAuthenticatedOrReadOnly]
    )
    def pdf_extract(self, request, pk=None):
        paper = Paper.objects.get(id=pk)
        pdf_file = paper.pdf_file_extract
        edited_file = paper.edited_file_extract

        if not pdf_file.name:
            return Response(status=status.HTTP_404_NOT_FOUND)

        if edited_file.name:
            edited_json = json.loads(edited_file.read())
            return Response(edited_json, status=status.HTTP_200_OK)

        html_bytes = paper.pdf_file_extract.read()
        b64_string = base64.b64encode(html_bytes)
        return Response(b64_string, status=status.HTTP_200_OK)

    @action(
        detail=True,
        methods=['post'],
        permission_classes=[AllowAny]
    )
    def edit_file_extract(self, request, pk=None):
        paper = self.get_object()
        data = request.data
        filename = f'{paper.id}.json'
        paper.edited_file_extract.save(
            filename,
            ContentFile(json.dumps(data).encode('utf8'))
        )
        return Response(status=status.HTTP_200_OK)

    def subscribed_hub_papers(self, request):
        feed_type = 'subscribed'
        user = request.user
        hubs = user.subscribed_hubs.all()
        page_number = int(request.GET['page'])
        start_date = datetime.datetime.fromtimestamp(
            int(request.GET.get('start_date__gte', 0)),
            datetime.timezone.utc
        )
        end_date = datetime.datetime.fromtimestamp(
            int(request.GET.get('end_date__lte', 0)),
            datetime.timezone.utc
        )
        ordering = self._set_hub_paper_ordering(request)

        if ordering == '-hot_score' and page_number == 1:
            papers = {}
            for hub in hubs.iterator():
                hub_name = hub.slug
                cache_key = get_cache_key('papers', hub_name)
                cache_hit = cache.get(cache_key)
                if cache_hit:
                    for hit in cache_hit:
                        paper_id = hit['id']
                        if paper_id not in papers:
                            papers[paper_id] = hit
            papers = list(papers.values())

            if len(papers) < 1:
                qs = self.get_queryset(
                    include_autopull=True
                ).order_by(
                    '-hot_score'
                )
                papers = qs.filter(hubs__in=hubs).distinct()
            else:
                papers = sorted(papers, key=lambda paper: -paper['hot_score'])
                papers = papers[:10]
                next_page = request.build_absolute_uri()
                if len(papers) < 10:
                    next_page = None
                else:
                    next_page = replace_query_param(next_page, 'page', 2)
                res = {
                    'count': len(papers),
                    'next': next_page,
                    'results': {
                        'data': papers,
                        'no_results': False,
                        'feed_type': feed_type
                    }
                }
                return Response(res, status=status.HTTP_200_OK)

        else:
            qs = self.get_queryset(
                include_autopull=True
                ).order_by(
                    '-hot_score'
                )
            papers = qs.filter(hubs__in=hubs).distinct()

        if papers.count() < 1:
            log_info(
                f"""
                    No hub papers found, retrieiving trending papers.
                    Page: {page_number}
                """
            )
            trending_pk = '0_-hot_score_today'
            cache_key_hub = get_cache_key('hub', trending_pk)
            cache_hit = cache.get(cache_key_hub)

            if cache_hit and page_number == 1:
                return Response(cache_hit)

            feed_type = 'all'
            papers = self.get_queryset().order_by('-hot_score')

        context = self.get_serializer_context()
        context['user_no_balance'] = True
        context['exclude_promoted_score'] = True
        context['include_wallet'] = False

        order_papers = self.calculate_paper_ordering(
            papers,
            ordering,
            start_date,
            end_date
        )

        page = self.paginate_queryset(order_papers)
        serializer = HubPaperSerializer(page, many=True, context=context)
        serializer_data = serializer.data

        return self.get_paginated_response(
            {
                'data': serializer_data,
                'no_results': False,
                'feed_type': feed_type
            }
        )

    def _set_hub_paper_ordering(self, request):
        ordering = request.query_params.get('ordering', None)
        # TODO send correct ordering from frontend
        if ordering == 'removed':
            ordering = 'removed'
        elif ordering == 'top_rated':
            ordering = '-score'
        elif ordering == 'most_discussed':
            ordering = '-discussed'
        elif ordering == 'newest':
            ordering = '-uploaded_date'
        elif ordering == 'hot':
            ordering = '-hot_score'
        else:
            ordering = '-score'
        return ordering

    def _get_filtered_papers(self, hub_id, ordering):
        # hub_id = 0 is the homepage
        # we aren't on a specific hub so don't filter by that hub_id
        if int(hub_id) == 0:
            qs = self.get_queryset(
                prefetch=False
            ).prefetch_related(
                *self.prefetch_lookups()
            )

            if 'removed' in ordering:
                qs = qs.filter(
                    is_removed=True
                )
            else:
                qs = qs.filter(
                    is_removed=False,
                    is_removed_by_user=False,
                )
        else:
            qs = self.get_queryset(
                prefetch=False
            ).filter(
                hubs__id__in=[int(hub_id)],
            ).prefetch_related(
                *self.prefetch_lookups()
            )

            if 'removed' in ordering:
                qs = qs.filter(
                    is_removed=True
                )
            else:
                qs = qs.filter(
                    is_removed=False,
                    is_removed_by_user=False,
                )
        return qs


class FeaturedPaperViewSet(viewsets.ModelViewSet):
    queryset = FeaturedPaper.objects.filter(
        paper__is_removed=False,
        user__is_suspended=False
    )
    serializer_class = FeaturedPaperSerializer
    throttle_classes = THROTTLE_CLASSES
    permission_classes = [IsAuthenticatedOrReadOnly]
    filter_backends = [DjangoFilterBackend, SearchFilter]
    search_fields = ['paper__title', 'user__id']
    filterset_fields = ['paper__title']

    def create(self, request):
        user = request.user
        orderings = request.data['ordering']
        featured_papers = []

        self.queryset.filter(user=user).delete()
        for ordering in orderings:
            ordinal = ordering['ordinal']
            paper_id = ordering['paper_id']
            featured_papers.append(
                FeaturedPaper(
                    ordinal=ordinal,
                    paper_id=paper_id,
                    user=user
                )
            )
        FeaturedPaper.objects.bulk_create(featured_papers)
        serializer = self.serializer_class(
            featured_papers,
            many=True
        )
        data = serializer.data

        return Response(data, status=200)

    def destroy(self, request, pk=None):
        featured = self.queryset.get(id=pk)
        res = featured.delete()
        return Response(res, status=200)

    def retrieve(self, request, pk=None):
        user = Author.objects.get(id=pk).user
        papers = self.queryset.filter(
            user=user,
            is_removed=False,
        ).order_by(
            'ordinal'
        )

        page = self.paginate_queryset(papers)
        if page is not None:
            serializer = self.serializer_class(page, many=True)
            return self.get_paginated_response(serializer.data)

        return Response(status=400)


class AdditionalFileViewSet(viewsets.ModelViewSet):
    queryset = AdditionalFile.objects.all()
    serializer_class = AdditionalFileSerializer
    throttle_classes = THROTTLE_CLASSES
    permission_classes = [
        IsAuthenticatedOrReadOnly
        & UpdateOrDeleteAdditionalFile
    ]

    def get_queryset(self):
        queryset = super().get_queryset()
        paper_id = get_paper_id_from_path(self.request)
        if paper_id is not None:
            queryset = queryset.filter(paper=paper_id)
        return queryset


class FigureViewSet(viewsets.ModelViewSet):
    queryset = Figure.objects.all()
    serializer_class = FigureSerializer
    throttle_classes = THROTTLE_CLASSES

    permission_classes = [
        IsModeratorOrVerifiedAuthor
    ]

    def get_queryset(self):
        return self.queryset

    def get_figures(self, paper_id, figure_type=None):
        # Returns all figures
        paper = Paper.objects.get(id=paper_id)
        figures = self.get_queryset().filter(paper=paper)

        if figure_type:
            figures = figures.filter(figure_type=figure_type)

        figures = figures.order_by('-figure_type', 'created_date')
        figure_serializer = self.serializer_class(figures, many=True)
        return figure_serializer.data

    @action(
        detail=True,
        methods=['post'],
        permission_classes=[
            IsAuthor
            & CreateOrUpdateIfAllowed
        ]
    )
    def add_figure(self, request, pk=None):
        user = request.user
        if user.is_anonymous:
            user = None

        created_location = None
        if request.query_params.get('created_location') == 'progress':
            created_location = Figure.CREATED_LOCATION_PROGRESS

        paper = Paper.objects.get(id=pk)
        figures = request.FILES.values()
        figure_type = request.data.get('figure_type')
        urls = []
        try:
            for figure in figures:
                fig = Figure.objects.create(
                    paper=paper,
                    file=figure,
                    figure_type=figure_type,
                    created_by=user,
                    created_location=created_location
                )
                urls.append({'id': fig.id, 'file': fig.file.url})
            return Response({'files': urls}, status=200)
        except Exception as e:
            log_error(e)
            return Response(status=500)

    @action(
        detail=True,
        methods=['delete'],
        permission_classes=[
            IsAuthor
            & CreateOrUpdateIfAllowed
        ]
    )
    def delete_figure(self, request, pk=None):
        figure = self.get_queryset().get(id=pk)
        figure.delete()
        return Response(status=200)

    @action(
        detail=True,
        methods=['get'],
        permission_classes=[IsAuthenticatedOrReadOnly]
    )
    def get_all_figures(self, request, pk=None):
        cache_key = get_cache_key('figure', pk)
        cache_hit = cache.get(cache_key)
        if cache_hit is not None:
            return Response(
                {'data': cache_hit},
                status=status.HTTP_200_OK
            )

        serializer_data = self.get_figures(pk)
        cache.set(cache_key, serializer_data, timeout=60*60*24*7)
        return Response(
            {'data': serializer_data},
            status=status.HTTP_200_OK
        )

    @action(
        detail=True,
        methods=['get'],
        permission_classes=[IsAuthenticatedOrReadOnly]
    )
    def get_preview_figures(self, request, pk=None):
        # Returns pdf preview figures
        serializer_data = self.get_figures(pk, figure_type=Figure.PREVIEW)
        return Response(
            {'data': serializer_data},
            status=status.HTTP_200_OK
        )

    @action(
        detail=True,
        methods=['get'],
        permission_classes=[IsAuthenticatedOrReadOnly]
    )
    def get_regular_figures(self, request, pk=None):
        # Returns regular figures
        serializer_data = self.get_figures(pk, figure_type=Figure.FIGURE)
        return Response(
            {'data': serializer_data},
            status=status.HTTP_200_OK
        )


def find_vote(user, paper, vote_type):
    vote = Vote.objects.filter(
        paper=paper,
        created_by=user,
        vote_type=vote_type
    )
    if vote:
        return True
    return False


def update_or_create_vote(request, user, paper, vote_type):
    vote = retrieve_vote(user, paper)

    if vote:
        vote.vote_type = vote_type
        vote.save()
        events_api.track_content_vote(user, vote, request)
        return get_vote_response(vote, 200)
    vote = create_vote(user, paper, vote_type)

    events_api.track_content_vote(user, vote, request)

    create_contribution.apply_async(
        (
            Contribution.UPVOTER,
            {'app_label': 'paper', 'model': 'vote'},
            user.id,
            paper.id,
            vote.id
        ),
        priority=3,
        countdown=10
    )
    return get_vote_response(vote, 201)


def get_vote_response(vote, status_code):
    """Returns Response with serialized `vote` data and `status_code`."""
    serializer = PaperVoteSerializer(vote)
    return Response(serializer.data, status=status_code)


def retrieve_vote(user, paper):
    try:
        return Vote.objects.get(
            paper=paper,
            created_by=user.id
        )
    except Vote.DoesNotExist:
        return None


def create_vote(user, paper, vote_type):
    vote = Vote.objects.create(
        created_by=user,
        paper=paper,
        vote_type=vote_type
    )
    return vote
