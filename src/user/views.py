from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.filters import SearchFilter, OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.decorators import action
from rest_framework.response import Response
from django.core.paginator import Paginator

from .models import User, Author
from .serializers import UserSerializer, AuthorSerializer
from .filters import *
from paper.models import *
from paper.serializers import *

class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        user = self.request.user
        if user.is_authenticated:
            return User.objects.filter(id=user.id)
        else:
            return []


class AuthorViewSet(viewsets.ModelViewSet):
    queryset = Author.objects.all()
    serializer_class = AuthorSerializer
    filter_backends = (SearchFilter, DjangoFilterBackend, OrderingFilter)
    filter_class = AuthorFilter
    search_fields = ('first_name', 'last_name')

    @action(
        detail=True,
        methods=['get'],
    )
    def get_authored_papers(self, request, pk=None):
        authors = Author.objects.filter(id=pk)
        if authors:
            author = authors.first()
            authored_papers = author.authored_papers.all()
            PAGE_SIZE = 20
            paginator = Paginator(authored_papers, PAGE_SIZE)
            page_num = request.GET["page"]
            page = paginator.page(page_num)
            url = request.build_absolute_uri('?')
            nextPageNum = int(page_num) + 1
            nextPage = url + "?page=" + str(nextPageNum)
            if not page.has_next():
                nextPage = None
            response = {
                'count': paginator.count,
                'has_next': page.has_next(),
                'next': nextPage,
                'results': PaperSerializer(authored_papers, many=True).data
            }
            return Response(response, status=200)
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
            import pdb; pdb.set_trace()
            authored_papers = author.authored_papers.all()
            PAGE_SIZE = 20
            paginator = Paginator(authored_papers, PAGE_SIZE)
            page_num = request.GET["page"]
            page = paginator.page(page_num)
            url = request.build_absolute_uri('?')
            nextPageNum = int(page_num) + 1
            nextPage = url + "?page=" + str(nextPageNum)
            if not page.has_next():
                nextPage = None
            response = {
                'count': paginator.count,
                'has_next': page.has_next(),
                'next': nextPage,
                'results': PaperSerializer(authored_papers, many=True).data
            }
            return Response(response, status=200)
        return Response(status=404)

