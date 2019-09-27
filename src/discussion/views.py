from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticatedOrReadOnly

from .models import Comment, Thread
from .serializers import CommentSerializer, ThreadSerializer
from reputation.permissions import CreateDiscussionThread


class ThreadViewSet(viewsets.ModelViewSet):
    serializer_class = ThreadSerializer

    # Optional attributes
    permission_classes = [IsAuthenticatedOrReadOnly & CreateDiscussionThread]

    def get_queryset(self):
        paper_id = self.get_paper_id_from_path()
        threads = Thread.objects.filter(paper=paper_id)
        return threads

    def get_paper_id_from_path(self):
        PAPER = 2
        paper_id = None
        path_parts = self.request.path.split('/')
        if path_parts[PAPER] == 'paper':
            try:
                paper_id = int(path_parts[PAPER + 1])
            except ValueError:
                print('Failed to get paper id')
        return paper_id


class CommentViewSet(viewsets.ModelViewSet):
    serializer_class = CommentSerializer

    permission_classes = [IsAuthenticatedOrReadOnly]

#    def comment(self, request, pk=None):
