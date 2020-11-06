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
from django.db.models import Sum, Q, F, Count
from django.contrib.contenttypes.models import ContentType
from utils.http import DELETE, POST, PATCH, PUT

from discussion.models import Thread
from discussion.serializers import (
    ThreadSerializer
)

from reputation.models import Distribution
from paper.models import Paper, Vote
from paper.views import PaperViewSet
from paper.serializers import PaperSerializer, HubPaperSerializer
from user.filters import AuthorFilter
from user.models import User, University, Author, Major
from user.permissions import UpdateAuthor, Censor
from user.serializers import (
    AuthorSerializer,
    AuthorEditableSerializer,
    UniversitySerializer,
    UserEditableSerializer,
    UserSerializer,
    UserActions,
    MajorSerializer
)

from utils.http import RequestMethods
from utils.permissions import CreateOrUpdateIfAllowed
from utils.throttles import THROTTLE_CLASSES
from datetime import timedelta
from django.utils import timezone
from utils.siftscience import events_api, decisions_api

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
        if self.request.GET.get('referral_code') or self.request.GET.get('invited_by'):
            return User.objects.filter(is_suspended=False)
        elif user.is_staff:
            return User.objects.all()
        elif user.is_authenticated:
            return User.objects.filter(id=user.id)
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

        user = request.user
        decisions_api.apply_bad_user_decision(user_to_censor, user)

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
                    hub_rep=Sum(
                        'reputation_records__amount',
                        filter=Q(
                            **time_filter,
                            reputation_records__hubs__in=[hub_id]
                        )
                    )
                ).order_by(F('hub_rep').desc(nulls_last=True))
            else:
                items = User.objects.filter(
                    is_active=True,
                    is_suspended=False,
                    probable_spammer=False,
                ).annotate(
                    hub_rep=Sum(
                        'reputation_records__amount',
                        filter=Q(**time_filter) & ~Q(reputation_records__distribution_type='REFERRAL')
                    )
                ).order_by(F('hub_rep').desc(nulls_last=True))
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


class UniversityViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = University.objects.all()
    serializer_class = UniversitySerializer
    filter_backends = (SearchFilter, DjangoFilterBackend, OrderingFilter)
    search_fields = ('name', 'city', 'state', 'country')
    permission_classes = [AllowAny]


class MajorViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Major.objects.all()
    serializer_class = MajorSerializer
    filter_backends = (SearchFilter, DjangoFilterBackend, OrderingFilter)
    search_fields = ('major', 'major_category')
    permission_classes = [AllowAny]


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
            authored_papers = author.authored_papers.filter(is_removed=False).order_by('-score')
            page = self.paginate_queryset(authored_papers)
            serializer = PaperSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        return Response(status=404)

    @action(
        detail=True,
        methods=['get'],
    )
    def get_user_discussions(self, request, pk=None):
        authors = Author.objects.filter(id=pk)
        if authors:
            author = authors.first()
            user = author.user
            user_discussions = Thread.objects.exclude(
                created_by=None
            ).filter(
                created_by=user,
                is_removed=False,
            ).prefetch_related('paper', 'comments').order_by('-id')
            page = self.paginate_queryset(user_discussions)
            serializer = ThreadSerializer(page, many=True)
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

            page = self.paginate_queryset(user_paper_uploads)
            serializer = PaperSerializer(page, many=True)
            response = self.get_paginated_response(serializer.data)

            return response
        return Response(status=404)
