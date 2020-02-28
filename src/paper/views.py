import datetime

from elasticsearch.exceptions import ConnectionError
from django.db.models import Count, Q, Prefetch, prefetch_related_objects, Avg, Max, IntegerField, F
from django.db.models.functions import Cast, Extract, Now
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.permissions import IsAuthenticatedOrReadOnly, IsAuthenticated
from rest_framework.response import Response
from requests.exceptions import (
    RequestException, MissingSchema, InvalidSchema, InvalidURL)

from .filters import PaperFilter
from .models import Flag, Paper, Vote
from discussion.models import Vote as DiscussionVote, Thread
from discussion.serializers import SimpleThreadSerializer
from .utils import get_csl_item, get_pdf_location_for_csl_item
from .permissions import (
    CreatePaper,
    FlagPaper,
    IsAuthor,
    IsModeratorOrVerifiedAuthor,
    UpdatePaper,
    UpvotePaper,
    DownvotePaper
)
from .serializers import (
    BookmarkSerializer,
    FlagSerializer,
    PaperSerializer,
    PaperVoteSerializer
)
from utils.http import RequestMethods, check_url_contains_pdf
from utils.serializers import EmptySerializer


class PaperViewSet(viewsets.ModelViewSet):
    queryset = Paper.objects.all()
    serializer_class = PaperSerializer
    filter_backends = (SearchFilter, DjangoFilterBackend, OrderingFilter)
    search_fields = ('title', 'doi')
    filter_class = PaperFilter
    ordering = ('-uploaded_date')

    permission_classes = [
        IsAuthenticatedOrReadOnly
        & CreatePaper
        & UpdatePaper
    ]

    def prefetch_lookups(self):
        return (
            #'users_who_bookmarked',
            'uploaded_by',
            'uploaded_by__bookmarks',
            'uploaded_by__author_profile',
            'uploaded_by__author_profile__user',
            'uploaded_by__subscribed_hubs',
            'authors',
            'authors__user',
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
            'threads',
            Prefetch(
                'votes',
                queryset=Vote.objects.filter(
                    created_by=self.request.user.id,
                ),
                to_attr="vote_created_by",
            ),
            Prefetch(
                'flags',
                queryset=Flag.objects.filter(
                    created_by=self.request.user.id,
                ),
                to_attr="flag_created_by",
            ),
        )

    def get_queryset(self, prefetch=True):
        if prefetch:
            return self.queryset.prefetch_related(*self.prefetch_lookups())
        else:
            return self.queryset

    @action(
        detail=True,
        methods=['put', 'patch', 'delete'],
        permission_classes=[IsAuthenticated, IsModeratorOrVerifiedAuthor]
    )
    def censor(self, request, pk=None):
        paper = self.get_object()
        paper.delete()
        return Response('Paper was deleted.', status=200)

    @action(
        detail=True,
        methods=['put', 'patch', 'delete'],
        permission_classes=[IsAuthenticated, IsModeratorOrVerifiedAuthor]
    )
    def censor_pdf(self, request, pk=None):
        paper = self.get_object()
        paper.file = None
        paper.url = ''
        paper.save()
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
        permission_classes=[IsAuthenticatedOrReadOnly]
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
        permission_classes=[FlagPaper]  # Also applies to delete_flag below
    )
    def flag(self, request, pk=None):
        paper = self.get_object()
        reason = request.data.get('reason')
        flag = Flag.objects.create(
            paper=paper,
            created_by=request.user,
            reason=reason
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
        permission_classes=[UpvotePaper]
    )
    def upvote(self, request, pk=None):
        paper = self.get_object()
        user = request.user

        vote_exists = find_vote(user, paper, Vote.UPVOTE)

        if vote_exists:
            return Response(
                'This vote already exists',
                status=status.HTTP_400_BAD_REQUEST
            )
        response = update_or_create_vote(user, paper, Vote.UPVOTE)
        return response

    @action(
        detail=True,
        methods=['post', 'put', 'patch'],
        permission_classes=[DownvotePaper]
    )
    def downvote(self, request, pk=None):
        paper = self.get_object()
        user = request.user

        vote_exists = find_vote(user, paper, Vote.DOWNVOTE)

        if vote_exists:
            return Response(
                'This vote already exists',
                status=status.HTTP_400_BAD_REQUEST
            )
        response = update_or_create_vote(user, paper, Vote.DOWNVOTE)
        return response

    @action(detail=False, methods=[RequestMethods.POST])
    def check_url(self, request):
        url = request.data.get('url', None)

        try:
            url_is_pdf = check_url_contains_pdf(url)
        except (MissingSchema, InvalidSchema, InvalidURL) as e:
            return Response(str(e), status=status.HTTP_400_BAD_REQUEST)

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
        """
        Retrieve bibliographic metadata and potential paper matches
        from the database for `url` (specified via request post data).
        """
        url = request.data.get('url')
        data = {'url': url}
        if not url:
            return Response(
                "search_by_url requests must specify 'url'",
                status=status.HTTP_400_BAD_REQUEST)
        try:
            url_is_pdf = check_url_contains_pdf(url)
            data['url_is_pdf'] = url_is_pdf
        except RequestException as error:
            return Response(
                f"Double check that URL is valid: {url}\n:{error}",
                status=status.HTTP_400_BAD_REQUEST)
        try:
            csl_item = get_csl_item(url)
        except Exception as error:
            data['warning'] = f"Generating csl_item failed with:\n{error}"
            csl_item = None
        if csl_item:
            url_is_unsupported_pdf = url_is_pdf and csl_item.get("URL") == url
            data['url_is_unsupported_pdf'] = url_is_unsupported_pdf
            csl_item.url_is_unsupported_pdf = url_is_unsupported_pdf
            data['csl_item'] = csl_item
            data['pdf_location'] = get_pdf_location_for_csl_item(csl_item)
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

    @action(detail=False, methods=['get'])
    def get_hub_papers(self, request):
        start_date = datetime.datetime.fromtimestamp(
            int(request.GET.get('start_date__gte', 0)),
            datetime.timezone.utc
        )
        end_date = datetime.datetime.fromtimestamp(
            int(request.GET.get('end_date__lte', 0)),
            datetime.timezone.utc
        )
        ordering = request.GET['ordering']

        # TODO send correct ordering from frontend
        if ordering == 'top_rated':
            ordering = '-score'
        elif ordering == 'most_discussed':
            ordering = '-discussed'
        elif ordering == 'newest':
            ordering = '-uploaded_date'
        elif ordering == 'hot':
            ordering = '-hot_score'

        hub_id = request.GET.get('hub_id', 0)

        threads_count = Count('threads')

        # hub_id = 0 is the homepage
        # we aren't on a specific hub so don't filter by that hub_id
        if int(hub_id) == 0:
            papers = self.get_queryset(prefetch=False).annotate(threads_count=threads_count).prefetch_related(*self.prefetch_lookups())
        else:
            papers = self.get_queryset(prefetch=False).annotate(threads_count=threads_count).filter(hubs=hub_id).prefetch_related(*self.prefetch_lookups())

        if 'hot_score' in ordering:
            INT_DIVISION = 142730 # (hours in a month) ** 1.8
            DISCUSSION_WEIGHT = 10 # num votes a comment is worth

            gravity = 1.8
            threads_c = Count('threads')
            comments_c = Count('threads__comments')
            replies_c = Count('threads__comments__replies')
            upvotes = Count( 'vote', filter=Q( vote__vote_type=Vote.UPVOTE,))
            downvotes = Count( 'vote', filter=Q( vote__vote_type=Vote.DOWNVOTE,))
            time_since_calc = (Extract(Now(), 'epoch') - Extract(Max('threads__created_date'), 'epoch')) / 3600

            numerator = (threads_c + comments_c + replies_c) * DISCUSSION_WEIGHT + (upvotes - downvotes)
            inverse_divisor = (INT_DIVISION / ((time_since_calc + 1) ** gravity))
            order_papers = papers.annotate(
                numerator=numerator,
                hot_score=numerator * inverse_divisor
            )
            if ordering[0] == '-':
                order_papers = order_papers.order_by(F('hot_score').desc(nulls_last=True), '-numerator')
            else:
                order_papers = order_papers.order_by(F('hot_score').asc(nulls_last=True), 'numerator')

        elif 'score' in ordering:
            upvotes = Count(
                'vote',
                filter=Q(
                    vote__vote_type=Vote.UPVOTE,
                    vote__updated_date__gte=start_date,
                    vote__updated_date__lte=end_date
                )
            )
            downvotes = Count(
                'vote',
                filter=Q(
                    vote__vote_type=Vote.DOWNVOTE,
                    vote__updated_date__gte=start_date,
                    vote__updated_date__lte=end_date
                )
            )

            all_time_upvotes = Count(
                'vote',
                filter=Q(
                    vote__vote_type=Vote.UPVOTE,
                )
            )
            all_time_downvotes = Count(
                'vote',
                filter=Q(
                    vote__vote_type=Vote.DOWNVOTE,
                )
            )

            order_papers = papers.annotate(
                score_in_time=upvotes - downvotes,
                score_all_time=all_time_upvotes + all_time_downvotes,
            ).order_by(ordering + '_in_time', ordering + '_all_time')

        elif 'discussed' in ordering:
            threads_c = Count(
                'threads',
                filter=Q(
                    threads__created_date__gte=start_date,
                    threads__created_date__lte=end_date
                )
            )
            comments = Count(
                'threads__comments',
                filter=Q(
                    threads__comments__created_date__gte=start_date,
                    threads__comments__created_date__lte=end_date
                )
            )
            all_time_comments = Count(
                'threads__comments',
            )
            order_papers = papers.annotate(
                discussed=threads_c + comments,
                discussed_secondary=threads_count + all_time_comments
            ).order_by(ordering, ordering + '_secondary')
        else:
            order_papers = papers.order_by(ordering)

        page = self.paginate_queryset(order_papers)
        serializer = PaperSerializer(page, many=True, context={'request': self.request, 'thread_serializer': EmptySerializer})
        return self.get_paginated_response({'data': serializer.data, 'no_results': False})

def find_vote(user, paper, vote_type):
    vote = Vote.objects.filter(
        paper=paper,
        created_by=user,
        vote_type=vote_type
    )
    if vote:
        return True
    return False


def update_or_create_vote(user, paper, vote_type):
    vote = retrieve_vote(user, paper)

    if vote:
        vote.vote_type = vote_type
        vote.save()
        return get_vote_response(vote, 200)
    vote = create_vote(user, paper, vote_type)
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
