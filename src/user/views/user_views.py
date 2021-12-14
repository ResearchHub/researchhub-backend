import hmac

from hashlib import sha1
from datetime import timedelta

from django.db import IntegrityError
from django.db.models import Sum, Q, F
from django.db.models.functions import Coalesce
from django.core.cache import cache
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.contrib.contenttypes.models import ContentType
from django.views.decorators.cache import cache_page
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status, viewsets
from rest_framework.utils.urls import replace_query_param
from rest_framework.permissions import (
    AllowAny,
    IsAuthenticated,
    IsAuthenticatedOrReadOnly
)
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.decorators import action
from rest_framework.response import Response

from discussion.models import Thread, Comment, Reply
from discussion.serializers import (
    DynamicThreadSerializer
)
from user.tasks import handle_spam_user_task, reinstate_user_task
from reputation.models import Distribution, Contribution
from reputation.serializers import DynamicContributionSerializer
from researchhub.settings import SIFT_WEBHOOK_SECRET_KEY, EMAIL_WHITELIST
from researchhub_document.serializers import DynamicPostSerializer
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from paper.models import Paper
from paper.utils import get_cache_key
from paper.views import PaperViewSet
from paper.serializers import (
    HubPaperSerializer,
    DynamicPaperSerializer
)
from user.filters import AuthorFilter
from user.models import (
    User,
    University,
    Author,
    Major,
    Verification,
    Follow,
)
from user.permissions import UpdateAuthor, Censor
from user.utils import reset_latest_acitvity_cache
from user.serializers import (
    AuthorSerializer,
    AuthorEditableSerializer,
    UniversitySerializer,
    UserEditableSerializer,
    UserSerializer,
    UserActions,
    MajorSerializer,
    VerificationSerializer,
)
from utils.http import DELETE, POST, PATCH, PUT
from utils.http import RequestMethods
from utils.permissions import CreateOrUpdateIfAllowed
from utils.throttles import THROTTLE_CLASSES
from django.db.models import Count
from hypothesis.related_models.hypothesis import Hypothesis

class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.filter(is_suspended=False)
    serializer_class = UserEditableSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    filter_backends = (DjangoFilterBackend,)
    filterset_fields = ['referral_code', 'invited_by']

    def get_serializer_class(self):
        if self.request.GET.get('referral_code') or self.request.GET.get('invited_by'):
            return UserSerializer
        else:
            return self.serializer_class

    def get_serializer_context(self):
        return {'get_subscribed': True, 'get_balance': True, 'user': self.request.user}

    def get_queryset(self):
        user = self.request.user
        qs = self.queryset
        author_profile = self.request.query_params.get('author_profile')
        if self.request.GET.get('referral_code') or self.request.GET.get('invited_by'):
            return qs
        elif author_profile:
            return User.objects.filter(author_profile=author_profile)
        elif user.is_staff:
            return qs
        elif user.is_authenticated:
            return qs.filter(id=user.id)
        else:
            return User.objects.none()

    @action(
        detail=False,
        methods=[POST],
        permission_classes=[IsAuthenticated, Censor]
    )
    def censor(self, request, pk=None):
        author_id = request.data.get('authorId')
        user_to_censor = User.objects.get(author_profile__id=author_id)
        user_to_censor.set_probable_spammer()
        user_to_censor.set_suspended()
        handle_spam_user_task(user_to_censor.id)

        return Response(
            {'message': 'User is Censored'},
            status=200
        )

    @action(
        detail=False,
        methods=[RequestMethods.GET],
    )
    def referral_rsc(self, request):
        """
        Gets the amount of RSC earned from referrals
        """

        distributions = Distribution.objects.filter(
            proof_item_content_type=ContentType.objects.get_for_model(User),
            proof_item_object_id=request.user.id
        ).exclude(recipient=request.user.id).aggregate(rsc_earned=Sum('amount'))

        amount = distributions.get('rsc_earned') or 0

        return Response({'amount': amount})

    @method_decorator(cache_page(60*60*6))
    @action(
        detail=False,
        methods=[RequestMethods.GET],
    )
    def leaderboard(self, request):
        """
        Leaderboard serves both Papers and Users
        """
        hub_id = request.GET.get('hub_id')
        if hub_id:
            hub_id = int(hub_id)

        leaderboard_type = request.GET.get('type', 'users')
        """
        createdByOptions can be values:
        1. created_date
        2. published_date
        """
        created_by_options = request.GET.get('dateOption', 'created_date')

        """
        Timeframe can be values:
        1. all_time
        2. today
        3. past_week
        4. past_month
        5. past_year
        """
        timeframe = request.GET.get('timeframe', 'all_time')

        context = {'request': request}
        serializer_kwargs = {}
        time_filter = {}
        if leaderboard_type == 'papers':
            if created_by_options == 'created_date':
                keyword = 'uploaded_date__gte'
            else:
                keyword = 'paper_publish_date__gte'
        elif leaderboard_type == 'users':
            keyword = 'reputation_records__created_date__gte'
        else:
            keyword = 'created_date__gte'

        if timeframe == 'today':
            time_filter = {keyword: timezone.now().date()}
        elif timeframe == 'past_week':
            time_filter = {keyword: timezone.now().date() - timedelta(days=7)}
        elif timeframe == 'past_month':
            time_filter = {keyword: timezone.now().date() - timedelta(days=30)}
        elif timeframe == 'past_year':
            if leaderboard_type == 'papers':
                keyword = 'uploaded_date__year__gte'
            else:
                keyword = 'created_date__year__gte'
            time_filter = {keyword: timezone.now().year}

        items = []
        if leaderboard_type == 'papers':
            serializerClass = DynamicPaperSerializer
            if hub_id and hub_id != 0:
                items = Paper.objects.exclude(
                    is_public=False,
                ).filter(
                    **time_filter,
                    hubs__in=[hub_id],
                    is_removed=False
                ).order_by('-score')
            else:
                items = Paper.objects.exclude(
                    is_public=False
                ).filter(
                    **time_filter,
                    is_removed=False
                ).order_by(
                    '-score'
                )
            serializer_kwargs = {
                '_include_fields': [
                    'id',
                    'abstract',
                    'boost_amount',
                    'discussion_count',
                    'file',
                    'hubs',
                    'paper_title',
                    'score',
                    'title',
                    'slug',
                    'uploaded_by',
                    'uploaded_date',
                ]
            }
        elif leaderboard_type == 'users':
            serializerClass = UserSerializer
            if hub_id and hub_id != 0:
                items = User.objects.filter(
                    is_active=True,
                    is_suspended=False,
                    probable_spammer=False,
                ).annotate(
                    hub_rep=Coalesce(Sum(
                        'reputation_records__amount',
                        filter=Q(
                            **time_filter,
                            reputation_records__hubs__in=[hub_id],
                        ) & ~Q(reputation_records__distribution_type__in=['REFERRAL', 'REWARD', 'REFERRAL_APPROVED']),
                    ), 0)
                ).order_by(F('hub_rep').desc(nulls_last=True), '-reputation')
            else:
                items = User.objects.filter(
                    is_active=True,
                    is_suspended=False,
                    probable_spammer=False,
                ).annotate(
                    hub_rep=Coalesce(Sum(
                        'reputation_records__amount',
                        filter=Q(**time_filter) & ~Q(reputation_records__distribution_type__in=['REFERRAL', 'REWARD', 'REFERRAL_APPROVED'])
                    ), 0)
                ).order_by(F('hub_rep').desc(nulls_last=True), '-reputation')
        elif leaderboard_type == 'authors':
            serializerClass = AuthorSerializer
            items = Author.objects.filter(user__is_suspended=False).order_by('-author_score')

        page = self.paginate_queryset(items)
        serializer = serializerClass(
            page,
            many=True,
            context=context,
            **serializer_kwargs
        )

        return self.get_paginated_response(serializer.data)

    @action(
        detail=True,
        methods=[RequestMethods.POST],
        permission_classes=[IsAuthenticated]
    )
    def follow(self, request, pk=None):
        data = request.data
        user = self.get_object()
        followee_id = data.get('followee_id')
        followee = Author.objects.get(id=followee_id).user

        try:
            follow = Follow.objects.create(
                user=user,
                followee=followee
            )
        except IntegrityError:
            follow = Follow.objects.get(
                user=user,
                followee=followee
            )
            follow.delete()

        is_following = user.following.filter(followee=followee).exists()
        return Response(is_following, status=200)

    @action(
        detail=True,
        methods=[RequestMethods.GET],
        permission_classes=[IsAuthenticated]
    )
    def following(self, request, pk=None):
        user = self.get_object()
        following_ids = user.following.values_list('followee')
        following = self.queryset.filter(id__in=following_ids)
        serializer = UserSerializer(following, many=True)
        data = {user['id']: user for user in serializer.data}
        return Response(data, status=200)

    @action(
        detail=True,
        methods=[RequestMethods.GET],
        permission_classes=[IsAuthenticated]
    )
    def check_follow(self, request, pk=None):
        user = request.user
        followee = Author.objects.get(id=pk).user
        is_following = user.following.filter(followee=followee).exists()
        return Response(is_following, status=200)


    @action(
        detail=False,
        methods=[RequestMethods.GET],
        permission_classes=[AllowAny]
    )
    def following_latest_activity(self, request):
        query_params = request.query_params
        ordering = query_params.get('ordering', '-created_date')
        hub_ids = query_params.get('hub_ids', '')
        page_number = query_params.get('page', 1)

        cache_hit = self._get_latest_activity_cache_hit(request, hub_ids)
        if cache_hit and page_number == 1:
            return Response(cache_hit)

        contributions = self._get_latest_activity_queryset(hub_ids, ordering)

        page = self.paginate_queryset(contributions)
        context = self._get_latest_activity_context()
        serializer = DynamicContributionSerializer(
            page,
            _include_fields=[
                'contribution_type',
                'created_date',
                'id',
                'source',
                'unified_document',
                'user'
            ],
            context=context,
            many=True,
        )
        response = self.get_paginated_response(serializer.data)

        if not cache_hit and page_number == 1:
            reset_latest_acitvity_cache(hub_ids, ordering)
        return response

    def _get_latest_activity_cache_hit(self, request, hub_ids):
        hub_ids_list = hub_ids.split(',')
        if len(hub_ids_list) > 1:
            results = {}
            count = 0
            previous = ''
            next_url = request.build_absolute_uri()
            for hub_id in hub_ids_list:
                cache_key = get_cache_key('contributions', hub_id)
                cache_hit = cache.get(cache_key)
                if not cache_hit:
                    return None

                for hit in cache_hit['results']:
                    hit_id = hit['id']
                    if hit_id not in results:
                        results[hit_id] = hit
                count += cache_hit.get('count', 1)

            results = list(results.values())
            results = sorted(
                results,
                key=lambda contrib: contrib['created_date'],
                reverse=True
            )[:10]
            next_url = replace_query_param(next_url, 'page', 2)

            data = {
                'count': count,
                'next': next_url,
                'previous': previous,
                'results': results
            }
            return data
        else:
            cache_key = get_cache_key('contributions', hub_ids)
            cache_hit = cache.get(cache_key)
            return cache_hit

    def _get_latest_activity_queryset(self, hub_ids, ordering):
        # following_ids = user.following.values_list('followee')
        contribution_type = [
            Contribution.SUBMITTER,
            Contribution.COMMENTER,
            Contribution.SUPPORTER,
        ]

        thread_content_type = ContentType.objects.get_for_model(Thread)
        comment_content_type = ContentType.objects.get_for_model(Comment)
        reply_content_type = ContentType.objects.get_for_model(Reply)
        removed_threads = Thread.objects.filter(is_removed=True)
        removed_comments = Comment.objects.filter(is_removed=True)
        removed_replies = Reply.objects.filter(is_removed=True)

        contributions = Contribution.objects.select_related(
            'content_type',
            'user',
            'user__author_profile',
            'unified_document',
        ).prefetch_related(
            'unified_document__hubs',
        ).filter(
            unified_document__is_removed=False,
            contribution_type__in=contribution_type,
        ).exclude(
            (
                (
                    Q(content_type=thread_content_type) &
                    Q(object_id__in=removed_threads)
                ) |
                (
                    Q(content_type=comment_content_type) &
                    Q(object_id__in=removed_comments)
                ) |
                (
                    Q(content_type=reply_content_type) &
                    Q(object_id__in=removed_replies)
                )
            )
        )

        if hub_ids:
            hub_ids = hub_ids.split(',')
            hub_ids = [int(i) for i in hub_ids]
            contributions = contributions.filter(
                unified_document__hubs__in=hub_ids
            ).order_by(
                ordering
            )
        else:
            contributions = contributions.order_by(
                ordering
            )
        contributions = contributions.distinct()
        return contributions

    def _get_latest_activity_context(self):
        context = {
            'doc_duds_get_documents': {
                '_include_fields': [
                    'created_date',
                    'id',
                    'slug',
                    'title',
                ]
            },
            'doc_duds_get_hubs': {
                '_include_fields': [
                    'name',
                    'is_locked',
                    'slug',
                    'is_removed',
                    'hub_image'
                ]
            },
            'rep_dcs_get_source': {
                '_include_fields': [
                    'abstract',
                    'amount',
                    'id',
                    'paper_title',
                    'slug',
                    'text',
                    'title'
                ]
            },
            'rep_dcs_get_unified_document': {
                '_include_fields': [
                    'created_date',
                    'documents',
                    'document_type',
                    'hubs',
                ]
            },
            'rep_dcs_get_user': {
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
            }
        }
        return context

    @action(
        detail=True,
        methods=[RequestMethods.GET],
        permission_classes=[IsAuthenticated]
    )
    def actions(self, request, pk=None):
        user_actions = UserActions(user=request.user)
        page = self.paginate_queryset(user_actions.serialized)
        return self.get_paginated_response(page)

    @action(
        detail=False,
        methods=[RequestMethods.PATCH],
    )
    def has_seen_first_coin_modal(self, request):
        user = request.user
        user = User.objects.get(pk=user.id)
        user.set_has_seen_first_coin_modal(True)
        serialized = UserSerializer(user)
        return Response(serialized.data, status=200)

    @action(
        detail=False,
        methods=[RequestMethods.PATCH],
    )
    def has_seen_orcid_connect_modal(self, request):
        user = request.user
        user = User.objects.get(pk=user.id)
        user.set_has_seen_orcid_connect_modal(True)
        serialized = UserSerializer(user)
        return Response(serialized.data, status=200)

    @action(
        detail=False,
        methods=[RequestMethods.PATCH],
    )
    def has_seen_stripe_modal(self, request):
        user = request.user
        user = User.objects.get(pk=user.id)
        user.set_has_seen_stripe_modal(True)
        serialized = UserSerializer(user)
        return Response(serialized.data, status=200)

    @action(
        detail=False,
        methods=[RequestMethods.POST],
        permission_classes=[IsAuthenticated, Censor],
    )
    def reinstate(self, request):
        author_id = request.data['author_id']
        user = Author.objects.get(id=author_id).user
        user.is_suspended = False
        user.probable_spammer = False
        user.save()
        reinstate_user_task(user.id)
        serialized = UserSerializer(user)
        return Response(serialized.data, status=200)

    @action(
        detail=False,
        methods=[RequestMethods.POST],
        permission_classes=[AllowAny],
    )
    def sift_check_user_content(self, request):
        # https://sift.com/developers/docs/python/decisions-api/decision-webhooks/authentication

        # Let's check whether this webhook actually came from Sift!
        # First let's grab the signature from the postback's headers
        postback_signature = request.headers.get("X-Sift-Science-Signature")

        # Next, let's try to assemble the signature on our side to verify
        key = SIFT_WEBHOOK_SECRET_KEY.encode('utf-8')
        postback_body = request.body

        h = hmac.new(key, postback_body, sha1)
        verification_signature = "sha1={}".format(h.hexdigest())

        if verification_signature == postback_signature:
            decision_id = request.data['decision']['id']
            user_id = request.data['entity']['id']
            user = User.objects.get(id=user_id)

            if not user.moderator or user.email not in EMAIL_WHITELIST:
                if 'mark_as_probable_spammer_content_abuse' in decision_id:
                    user.set_probable_spammer()
                elif 'suspend_user_content_abuse' in decision_id:
                    user.set_suspended(is_manual=False)
            serialized = UserSerializer(user)
            return Response(serialized.data, status=200)
        else:
            raise Exception('Sift verification signature mismatch')


class UniversityViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = University.objects.all()
    serializer_class = UniversitySerializer
    filter_backends = (SearchFilter, DjangoFilterBackend, OrderingFilter)
    search_fields = ('name', 'city', 'state', 'country')
    permission_classes = [AllowAny]

    @method_decorator(cache_page(60*60*6))
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @method_decorator(cache_page(60*60*6))
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)


class MajorViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Major.objects.all()
    serializer_class = MajorSerializer
    filter_backends = (SearchFilter, DjangoFilterBackend, OrderingFilter)
    search_fields = ('major', 'major_category')
    permission_classes = [AllowAny]


class VerificationViewSet(viewsets.ModelViewSet):
    queryset = Verification.objects.all()
    serializer_class = VerificationSerializer

    @action(
        detail=False,
        methods=['post'],
    )
    def bulk_upload(self, request):
        images = request.data.getlist('images')
        for image in images:
            Verification.objects.create(
                file=image,
                user=request.user,
            )

        return Response({'message': 'Verification was uploaded!'})


class AuthorViewSet(viewsets.ModelViewSet):
    queryset = Author.objects.all()
    serializer_class = AuthorSerializer
    filter_backends = (SearchFilter, DjangoFilterBackend, OrderingFilter)
    filter_class = AuthorFilter
    search_fields = ('first_name', 'last_name')
    permission_classes = [
        IsAuthenticatedOrReadOnly
        & UpdateAuthor
        & CreateOrUpdateIfAllowed
    ]
    throttle_classes = THROTTLE_CLASSES

    def create(self, request, *args, **kwargs):
        '''Override to use an editable serializer.'''
        serializer = AuthorEditableSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED,
            headers=headers
        )

    def update(self, request, *args, **kwargs):
        '''Override to use an editable serializer.'''
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = AuthorEditableSerializer(
            instance,
            data=request.data,
            partial=partial
        )
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)

        if getattr(instance, '_prefetched_objects_cache', None):
            # If 'prefetch_related' has been applied to a queryset, we need to
            # forcibly invalidate the prefetch cache on the instance.
            instance._prefetched_objects_cache = {}

        return Response(serializer.data)

    @action(
        detail=True,
        methods=['get'],
    )
    def get_authored_papers(self, request, pk=None):
        author = self.get_object()
        prefetch_lookups = PaperViewSet.prefetch_lookups(self)
        authored_papers = author.authored_papers.filter(
            is_removed=False
        ).prefetch_related(
            *prefetch_lookups,
        ).order_by('-score')
        context = self._get_authored_papers_context()
        page = self.paginate_queryset(authored_papers)
        serializer = DynamicPaperSerializer(
            page,
            _include_fields=[
                'id',
                'abstract',
                'authors',
                'boost_amount',
                'file',
                'first_preview',
                'hubs',
                'paper_title',
                'score',
                'title',
                'uploaded_by',
                'uploaded_date',
                'url',
                'paper_publish_date',
                'slug',
            ],
            many=True,
            context=context
        )
        response = self.get_paginated_response(serializer.data)
        return response

    def _get_authored_papers_context(self):
        context = {
            'pap_dps_get_authors': {
                '_include_fields': [
                    'id',
                    'first_name',
                    'last_name',
                    'profile_image',
                ]
            },
            'pap_dps_get_uploaded_by': {
                '_include_fields': [
                    'id',
                    'author_profile',
                ]
            },
            'pap_dps_get_first_preview': {
                '_include_fields': [
                    'file',
                ]
            },
            'usr_dus_get_author_profile': {
                '_include_fields': [
                    'id',
                    'first_name',
                    'last_name',
                    'profile_image'
                ]
            },
            'doc_duds_get_hubs': {
                '_include_fields': [
                    'id',
                    'name',
                    'slug',
                    'hub_image',
                ]
            }
        }
        return context


    def _get_contribution_context(self, filter_by_user_id):
        context = {
            '_config': {
                'filter_by_user_id': filter_by_user_id,
            },
            'doc_duds_get_documents': {
                '_include_fields': [
                    'promoted',
                    'abstract',
                    'aggregate_citation_consensus',
                    'created_by',
                    'created_date',
                    'hot_score',
                    'hubs',
                    'id',
                    'discussion_count',
                    'paper_title',
                    'preview_img',
                    'renderable_text',
                    'score',
                    'slug',
                    'title',
                    'uploaded_by',
                    'uploaded_date',
                    ]
            },
            'rep_dcs_get_author': {
                '_include_fields': [
                    'id',
                    'first_name',
                    'last_name',
                    'profile_image',
                ]
            },
            'dis_dts_get_created_by': {
                '_include_fields': [
                    'id',
                    'author_profile',
                ]
            },
            'rep_dcs_get_unified_document': {
                '_include_fields': [
                    'id',
                    'document_type',
                    'documents',
                    'hubs',
                ]
            },
            'rep_dcs_get_source': {
                '_include_fields': [
                    'replies',
                    'content_type',
                    'promoted',
                    'comments',
                    'discussion_type',
                    'amount',
                    'paper_title',
                    'slug',
                    'block_key',
                    'comment_count',
                    'context_title',
                    'created_by',
                    'created_date',
                    'created_location',
                    'entity_key',
                    'external_metadata',
                    'hypothesis',
                    'citation',
                    'id',
                    'is_public',
                    'is_removed',
                    'paper_slug',
                    'paper',
                    'post_slug',
                    'post',
                    'plain_text',
                    'promoted',
                    'score',
                    'source',
                    'text',
                    'title',
                    'user_flag',
                    'user_vote',
                    'was_edited',
                    'document_meta',
                ]
            },
            'dis_dts_get_paper': {
                '_include_fields': [
                    'id',
                    'slug',
                ]
            },
            'dis_dts_get_post': {
                '_include_fields': [
                    'id',
                    'slug',
                ]
            },
            'doc_duds_get_hubs': {
                '_include_fields': [
                    'name',
                    'slug',
                ]
            }
        }
        return context

    @action(
        detail=True,
        methods=['get'],
    )
    def contributions(self, request, pk=None):
        author = self.get_object()

        query_params = request.query_params
        ordering = query_params.get('ordering', '-created_date')
        asset_type = query_params.get('type', 'overview')
        contributions = self._get_author_contribution_queryset(author.id, ordering, asset_type)

        page = self.paginate_queryset(contributions)
        context = self._get_contribution_context(author.user_id)
        serializer = DynamicContributionSerializer(
            page,
            _include_fields=[
                'contribution_type',
                'created_date',
                'id',
                'source',
                'created_by',
                'unified_document',
                'author'
            ],
            context=context,
            many=True,
        )
        response = self.get_paginated_response(serializer.data)

        return response

    def _get_author_threads_participated(self, author_id):
        author = self.get_object()
        user = author.user

        user_replies = Reply.objects.filter(
            created_by_id=user.id,
            is_removed=False
        )
        user_comments = Comment.objects.filter(
            Q(is_removed=False) &
            (
                Q(created_by_id=user.id) |
                Q(id__in=[r.object_id for r in user_replies])
            )
        )
        user_threads = Thread.objects.filter(
            Q(is_removed=False) &
            (
                Q(created_by_id=user.id) |
                Q(id__in=[c.parent_id for c in user_comments])
            )
        )

        return user_threads

    def _get_author_contribution_queryset(self, author_id, ordering, asset_type):
        author = self.get_object()
        user = author.user
        author_threads = self._get_author_threads_participated(author_id)
        thread_content_type = ContentType.objects.get_for_model(Thread)
        post_content_type = ContentType.objects.get_for_model(ResearchhubPost)
        paper_content_type = ContentType.objects.get_for_model(Paper)
        hypothesis_content_type = ContentType.objects.get_for_model(Hypothesis)

        types = asset_type.split(",")

        query = Q()
        for asset_type in types:
            if asset_type == "overview":
                query |= Q(
                    Q(
                        unified_document__is_removed=False,
                        content_type=thread_content_type,
                        object_id__in=author_threads,
                        contribution_type__in=[
                            Contribution.COMMENTER
                        ],                        
                    ) |
                    Q(
                        unified_document__is_removed=False,
                        user__author_profile=author_id,
                        contribution_type__in=[
                            Contribution.SUBMITTER,
                            Contribution.SUPPORTER
                        ],
                    )
                )
            elif asset_type == "discussion":
                query |= Q(
                    unified_document__is_removed=False,
                    user__author_profile=author_id,
                    content_type_id=post_content_type,
                    contribution_type__in=[
                        Contribution.SUBMITTER
                    ],
                )
            elif asset_type == "hypothesis":
                query |= Q(
                    unified_document__is_removed=False,
                    user__author_profile=author_id,
                    content_type_id=hypothesis_content_type,
                    contribution_type__in=[
                        Contribution.SUBMITTER
                    ],
                )
            elif asset_type == "comment":
                query |= Q(
                    unified_document__is_removed=False,
                    content_type=thread_content_type,
                    object_id__in=author_threads,
                    contribution_type__in=[
                        Contribution.COMMENTER
                    ],
                )
            elif asset_type == "paper":
                query |= Q(
                    unified_document__is_removed=False,
                    user__author_profile=author_id,
                    content_type_id=paper_content_type,
                    contribution_type__in=[
                        Contribution.SUBMITTER
                    ],
                )
            else:
                raise Exception('Unrecognized asset type')


        return Contribution.objects.filter(query).select_related(
            'content_type',
            'user',
            'user__author_profile',
            'unified_document',
        ).order_by(ordering)

    @action(
        detail=True,
        methods=['get'],
    )
    def get_user_discussions(self, request, pk=None):
        author = self.get_object()
        user = author.user

        if user:
            user_discussions = user.thread_set.filter(
                is_removed=False
            ).order_by('-id')
        else:
            user_discussions = self.queryset.none()

        page = self.paginate_queryset(user_discussions)
        context = self._get_user_discussion_context()
        serializer = DynamicThreadSerializer(
            page,
            _include_fields=[
                'id',
                'comment_count',
                'created_by',
                'created_date',
                'paper',
                'post',
                'score',
                'text',
            ],
            many=True,
            context=context
        )
        return self.get_paginated_response(serializer.data)

    def _get_user_discussion_context(self):
        context = {
            'dis_dts_get_created_by': {
                '_include_fields': [
                    'id',
                    'author_profile',
                ]
            },
            'dis_dts_get_paper': {
                '_include_fields': [
                    'id',
                    'slug',
                ]
            },
            'dis_dts_get_post': {
                '_include_fields': [
                    'id',
                    'slug',
                ]
            },
            'usr_dus_get_author_profile': {
                '_include_fields': [
                    'id',
                    'first_name',
                    'last_name',
                    'profile_image'
                ]
            },
        }
        return context

    @action(
        detail=True,
        methods=['get'],
    )
    def get_user_contributions(self, request, pk=None):
        author = self.get_object()
        user = author.user

        if user:
            prefetch_lookups = PaperViewSet.prefetch_lookups(self)
            user_paper_uploads = user.papers.filter(
                is_removed=False
            ).prefetch_related(
                *prefetch_lookups
            )
        else:
            user_paper_uploads = self.queryset.none()

        context = self._get_user_contributions_context()
        page = self.paginate_queryset(user_paper_uploads)
        serializer = DynamicPaperSerializer(
            page,
            _include_fields=[
                'id',
                'abstract',
                'boost_amount',
                'file',
                'hubs',
                'paper_title',
                'score',
                'title',
                'slug',
                'uploaded_by',
                'uploaded_date',
            ],
            many=True,
            context=context
        )
        response = self.get_paginated_response(serializer.data)

        return response

    def _get_user_contributions_context(self):
        context = {
            'pap_dps_get_uploaded_by': {
                '_include_fields': [
                    'id',
                    'author_profile',
                ]
            },
            'usr_dus_get_author_profile': {
                '_include_fields': [
                    'id',
                    'first_name',
                    'last_name',
                    'profile_image'
                ]
            },
            'doc_duds_get_hubs': {
                '_include_fields': [
                    'id',
                    'name',
                    'slug',
                    'hub_image',
                ]
            }
        }
        return context

    @action(
        detail=True,
        methods=['get'],
    )
    def get_user_posts(self, request, pk=None):
        author = self.get_object()
        user = author.user

        if user:
            user_posts = user.created_posts.all().prefetch_related(
                'unified_document',
                'purchases'
            )
        else:
            user_posts = self.queryset.none()

        context = self._get_user_posts_context()
        page = self.paginate_queryset(user_posts)
        serializer = DynamicPostSerializer(
            page,
            _include_fields=[
                'id',
                'created_by',
                'hubs',
                'boost_amount',
                'renderable_text',
                'score',
                'slug',
                'title',
            ],
            many=True,
            context=context
        )
        response = self.get_paginated_response(serializer.data)
        return response

    def _get_user_posts_context(self):
        context = {
            'doc_dps_get_created_by': {
                '_include_fields': [
                    'id',
                    'author_profile',
                ]
            },
            'usr_dus_get_author_profile': {
                '_include_fields': [
                    'id',
                    'first_name',
                    'last_name',
                    'profile_image'
                ]
            },
            'doc_dps_get_hubs': {
                '_include_fields': [
                    'id',
                    'name',
                    'slug',
                    'hub_image',
                ]
            }
        }
        return context
