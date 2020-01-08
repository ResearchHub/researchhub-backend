from rest_framework import viewsets
from rest_framework.permissions import (
    AllowAny,
    IsAuthenticated,
    IsAuthenticatedOrReadOnly
)
from rest_framework.filters import SearchFilter, OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.decorators import action
from rest_framework.response import Response

from discussion.models import Comment, Reply, Thread
from discussion.serializers import (
    CommentSerializer,
    ReplySerializer,
    ThreadSerializer
)
from paper.models import Paper
from paper.serializers import PaperSerializer
from user.filters import AuthorFilter
from user.models import User, University, Author
from user.permissions import UpdateAuthor
from user.serializers import (
    AuthorSerializer,
    UniversitySerializer,
    UserSerializer,
    UserActions
)
from utils.http import RequestMethods


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        user = self.request.user
        if user.is_staff:
            return User.objects.all()
        elif user.is_authenticated:
            return User.objects.filter(id=user.id)
        else:
            return User.objects.none()

    @action(
        detail=True,
        methods=[RequestMethods.GET],
        permission_classes=[IsAuthenticated]
    )
    def actions(self, request, pk=None):
        user = request.user
        if not user.is_staff:
            pk = user.id
        user_actions = UserActions(pk)
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

            user_comments = Comment.objects.filter(created_by=user)
            user_replies = Reply.objects.filter(created_by=user)
            user_paper_uploads = Paper.objects.filter(uploaded_by=user)

            user_comments_count = len(user_comments)
            user_replies_count = len(user_replies)
            user_paper_uploads_count = len(user_paper_uploads)
            count = (
                user_comments_count
                + user_replies_count
                + user_paper_uploads_count
            )

            user_comments = list(
                user_comments[comment_offset:(comment_offset + PAGE_SIZE)]
            )
            user_replies = list(
                user_replies[reply_offset:(reply_offset + PAGE_SIZE)]
            )
            user_paper_uploads = list(
                user_paper_uploads[
                    paper_upload_offset:(paper_upload_offset + PAGE_SIZE)
                ]
            )

            contributions = user_comments + user_replies + user_paper_uploads
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
                    serialized_data = ReplySerializer(contribution).data
                    serialized_data['type'] = 'reply'
                    serialized_contributions.append(serialized_data)

                elif (isinstance(contribution, Comment)):
                    offsets['comment_offset'] = offsets['comment_offset'] + 1
                    serialized_data = CommentSerializer(contribution).data
                    serialized_data['type'] = 'comment'
                    serialized_contributions.append(serialized_data)

                elif (isinstance(contribution, Paper)):
                    offsets['paper_upload_offset'] = (
                        offsets['paper_upload_offset'] + 1
                    )
                    serialized_data = PaperSerializer(contribution).data
                    serialized_data['type'] = 'paper'
                    serialized_contributions.append(serialized_data)

            has_next = False
            if offsets['comment_offset'] < user_comments_count:
                has_next = True
            if offsets['reply_offset'] < user_replies_count:
                has_next = True
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
