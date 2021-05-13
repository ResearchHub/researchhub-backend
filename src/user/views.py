from django.db import IntegrityError
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status, viewsets
from rest_framework.permissions import (
    AllowAny,
    IsAuthenticated,
    IsAuthenticatedOrReadOnly
)
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Sum, Q, F
from django.db.models.functions import Coalesce
from django.contrib.contenttypes.models import ContentType
from utils.http import DELETE, POST, PATCH, PUT

from discussion.models import Thread
from discussion.serializers import (
    ThreadSerializer
)

from user.tasks import handle_spam_user_task, reinstate_user_task
from reputation.models import Distribution, Contribution
from reputation.serializers import ContributionSerializer
from paper.models import Paper
from paper.views import PaperViewSet
from paper.serializers import PaperSerializer, HubPaperSerializer
from user.filters import AuthorFilter
from user.models import (
    User,
    University,
    Author,
    Major,
    Verification,
    Follow
)
from user.permissions import UpdateAuthor, Censor
from user.serializers import (
    AuthorSerializer,
    AuthorEditableSerializer,
    UniversitySerializer,
    UserEditableSerializer,
    UserSerializer,
    UserActions,
    MajorSerializer,
    VerificationSerializer
)

from utils.http import RequestMethods
from utils.permissions import CreateOrUpdateIfAllowed
from utils.throttles import THROTTLE_CLASSES
from datetime import timedelta
from django.utils import timezone


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
            serializerClass = HubPaperSerializer
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
            context={'request': request}
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
        user = request.user
        # following_ids = user.following.values_list('followee')
        contribution_type = [
            Contribution.COMMENTER,
            Contribution.SUPPORTER,
            Contribution.VIEWER
        ]
        contributions = Contribution.objects.prefetch_related(
            'paper',
            'user',
            'paper__uploaded_by'
        ).filter(
            contribution_type__in=contribution_type
        )

        if hub_ids:
            hub_ids = hub_ids.split(',')
            hub_ids = [int(i) for i in hub_ids]
            contributions = contributions.filter(
                paper__hubs__in=hub_ids
                # user__in=following_ids
            ).order_by(
                ordering
            )
        else:
            contributions = contributions.order_by(
                ordering
            )
        contributions = contributions.distinct()
        page = self.paginate_queryset(contributions)
        serializer = ContributionSerializer(page, many=True)
        response = self.get_paginated_response(serializer.data)
        return response

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
        authors = Author.objects.filter(id=pk)
        if authors:
            author = authors.first()
            prefetch_lookups = PaperViewSet.prefetch_lookups(self)
            authored_papers = author.authored_papers.filter(
                is_removed=False
            ).prefetch_related(
                *prefetch_lookups,
            ).order_by('-score')
            context = self.get_serializer_context()
            context['include_wallet'] = False
            page = self.paginate_queryset(authored_papers)
            serializer = PaperSerializer(page, many=True, context=context)
            return self.get_paginated_response(serializer.data)
        return Response(status=404)

    @action(
        detail=True,
        methods=['get'],
    )
    def get_user_discussions(self, request, pk=None):
        authors = Author.objects.filter(id=pk)
        if authors:
            context = self.get_serializer_context()
            context['include_wallet'] = False
            author = authors.first()
            user = author.user
            user_discussions = Thread.objects.exclude(
                created_by=None
            ).filter(
                created_by=user,
                is_removed=False,
            ).prefetch_related(
                'paper', 'comments',
            ).order_by('-id')
            page = self.paginate_queryset(user_discussions)
            serializer = ThreadSerializer(page, many=True, context=context)
            return self.get_paginated_response(serializer.data)
        return Response(status=404)

    @action(
        detail=True,
        methods=['get'],
    )
    def get_user_contributions(self, request, pk=None):
        authors = Author.objects.filter(id=pk)
        if authors:
            author = authors.first()
            user = author.user

            prefetch_lookups = PaperViewSet.prefetch_lookups(self)
            user_paper_uploads = Paper.objects.exclude(
                uploaded_by=None
            ).filter(
                uploaded_by=user,
                is_removed=False,
            ).prefetch_related(
                *prefetch_lookups
            )

            context = self.get_serializer_context()
            context['include_wallet'] = False
            page = self.paginate_queryset(user_paper_uploads)
            serializer = PaperSerializer(page, many=True, context=context)
            response = self.get_paginated_response(serializer.data)

            return response
        return Response(status=404)
