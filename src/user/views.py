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

from discussion.models import Comment, Reply, Thread
from discussion.serializers import (
    CommentSerializer,
    ReplySerializer,
    ThreadSerializer
)

from paper.models import Paper
from paper.views import PaperViewSet
from paper.serializers import PaperSerializer
from user.filters import AuthorFilter
from user.models import User, University, Author
from user.permissions import UpdateAuthor
from user.serializers import (
    AuthorSerializer,
    AuthorEditableSerializer,
    UniversitySerializer,
    UserEditableSerializer,
    UserSerializer,
    UserActions
)

from utils.http import RequestMethods    

class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserEditableSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get_serializer_context(self):
        return {'get_subscribed': True, 'get_balance': True}

    def get_queryset(self):
        user = self.request.user
        if user.is_staff:
            return User.objects.all()
        elif user.is_authenticated:
            return User.objects.filter(id=user.id)
        else:
            return User.objects.none()
    
    @action(
        detail=False,
        methods=[RequestMethods.GET],
    )
    def leaderboard(self, request):
        hub_id = request.GET.get('hub_id')
        if hub_id:
            hub_id = int(hub_id)
        if hub_id != 0:
            users = User.objects.all().annotate(
                hub_rep=Sum(
                    'reputation_records__amount',
                    filter=Q(reputation_records__hubs__in=[hub_id])
                )
            ).order_by(F('hub_rep').desc(nulls_last=True))
        else:
            users = User.objects.order_by('-reputation')
        page = self.paginate_queryset(users)
        serializer = UserSerializer(page, many=True)

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


class UniversityViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = University.objects.all()
    serializer_class = UniversitySerializer
    filter_backends = (SearchFilter, DjangoFilterBackend, OrderingFilter)
    search_fields = ('name', 'city', 'state', 'country')
    permission_classes = [AllowAny]


class AuthorViewSet(viewsets.ModelViewSet):
    queryset = Author.objects.all()
    serializer_class = AuthorSerializer
    filter_backends = (SearchFilter, DjangoFilterBackend, OrderingFilter)
    filter_class = AuthorFilter
    search_fields = ('first_name', 'last_name')
    permission_classes = [IsAuthenticatedOrReadOnly & UpdateAuthor]

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
            authored_papers = author.authored_papers.all()
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
            user_discussions = Thread.objects.filter(created_by=user)
            page = self.paginate_queryset(user_discussions)
            serializer = ThreadSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        return Response(status=404)

    @action(
        detail=True,
        methods=['get'],
    )
    def get_user_contributions(self, request, pk=None):
        def sort(contribution):
            return contribution.updated_date

        authors = Author.objects.filter(id=pk)
        if authors:
            author = authors.first()
            user = author.user
            PAGE_SIZE = 20

            comment_offset = int(request.GET['commentOffset'])
            reply_offset = int(request.GET['replyOffset'])
            paper_upload_offset = int(request.GET['paperUploadOffset'])

            prefetch_lookups = PaperViewSet.prefetch_lookups(self)
            user_paper_uploads = Paper.objects.filter(uploaded_by=user).prefetch_related(*prefetch_lookups)

            user_paper_uploads_count = len(user_paper_uploads)
            count = (
                user_paper_uploads_count
            )

            user_paper_uploads = list(
                user_paper_uploads[
                    paper_upload_offset:(paper_upload_offset + PAGE_SIZE)
                ]
            )

            contributions = user_paper_uploads
            contributions.sort(reverse=True, key=sort)
            contributions = contributions[0:PAGE_SIZE]
            offsets = {
                "comment_offset": comment_offset,
                "reply_offset": reply_offset,
                "paper_upload_offset": paper_upload_offset,
            }

            serialized_contributions = []
            for contribution in contributions:
                if (isinstance(contribution, Reply)):
                    offsets['reply_offset'] = offsets['reply_offset'] + 1
                    serialized_data = ReplySerializer(
                        contribution,
                        context={'request': request}
                    ).data
                    serialized_data['type'] = 'reply'
                    serialized_contributions.append(serialized_data)

                elif (isinstance(contribution, Comment)):
                    offsets['comment_offset'] = offsets['comment_offset'] + 1
                    serialized_data = CommentSerializer(
                        contribution,
                        context={'request': request}
                    ).data
                    serialized_data['type'] = 'comment'
                    serialized_contributions.append(serialized_data)

                elif (isinstance(contribution, Paper)):
                    offsets['paper_upload_offset'] = (
                        offsets['paper_upload_offset'] + 1
                    )
                    serialized_data = PaperSerializer(
                        contribution,
                        context={'request': request}
                    ).data
                    serialized_data['type'] = 'paper'
                    serialized_contributions.append(serialized_data)

            has_next = False
            if offsets['paper_upload_offset'] < user_paper_uploads_count:
                has_next = True

            response = {
                'count': count,
                'has_next': has_next,
                'results': serialized_contributions,
                'offsets': offsets
            }
            return Response(response, status=200)
        return Response(status=404)
